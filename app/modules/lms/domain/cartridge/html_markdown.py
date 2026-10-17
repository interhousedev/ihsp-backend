"""HTML pages of a cartridge to step markdown, and step markdown back to HTML.

Text blocks hold markdown (GFM tables, ``$...$`` math, images as
``![alt](/files/<id>)``). Cartridge pages are HTML from many tools (Canvas,
OpenStax, MIT OCW, Moodle), so the conversion is forgiving: unknown tags keep
their text, scripts and styles are dropped, MathML keeps its TeX annotation when
there is one. Every ``src``/``href`` passes through a callback that rewrites it
(to an uploaded file, or to a plain link).
"""

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final, Literal

UrlKind = Literal["link", "image", "media"]
UrlRewriter = Callable[[str, UrlKind], str | None]

_VOID: Final = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta"}
    | {"param", "source", "track", "wbr"}
)
_DROP: Final = frozenset(
    {"script", "style", "head", "noscript", "template", "button", "select", "form"}
)
_BLOCK: Final = frozenset(
    {"p", "div", "section", "article", "header", "footer", "main", "figure"}
    | {"aside", "nav", "body", "html", "figcaption", "dl", "dd", "dt", "center"}
    | {"details", "summary", "caption"}
)
_VIDEO_HOSTS: Final = re.compile(
    r"(youtube\.com|youtu\.be|youtube-nocookie\.com|vimeo\.com)", re.IGNORECASE
)
_ESCAPE: Final = re.compile(r"([\\`*_\[\]])")
_SPACES: Final = re.compile(r"[ \t\r\n\f\v]+")


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list["_Node | str"] = field(default_factory=list)


class _TreeBuilder(HTMLParser):
    """A lenient DOM: unclosed tags close with their parent."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {k.lower(): v or "" for k, v in attrs})
        if node.tag in {"p", "li"}:
            self._close_open(node.tag)
        self.stack[-1].children.append(node)
        if node.tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {k.lower(): v or "" for k, v in attrs})
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == name:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)

    def _close_open(self, tag: str) -> None:
        if len(self.stack) > 1 and self.stack[-1].tag == tag:
            self.stack.pop()


@dataclass(slots=True)
class HtmlConversion:
    """Markdown of a page plus the video links found in its iframes."""

    markdown: str
    title: str
    videos: list[str]


class _Renderer:
    def __init__(self, rewrite: UrlRewriter) -> None:
        self.rewrite = rewrite
        self.videos: list[str] = []
        self.title = ""

    # - - - blocks - - -

    def blocks(self, node: _Node, depth: int = 0) -> str:
        parts: list[str] = []
        inline: list[str] = []

        def flush() -> None:
            text = "".join(inline).strip()
            inline.clear()
            if text:
                parts.append(text)

        for item in node.children:
            if isinstance(item, str):
                inline.append(_text(item))
                continue
            block = self.block(item, depth)
            if block is None:
                inline.append(self.inline(item))
            else:
                flush()
                if block.strip():
                    parts.append(block.strip("\n"))
        flush()
        return "\n\n".join(parts)

    def block(self, node: _Node, depth: int) -> str | None:  # noqa: C901 - a dispatch
        tag = node.tag
        if tag == "title" or tag in _DROP:
            return None
        if tag in _BLOCK:
            return self.blocks(node, depth)
        if len(tag) == 2 and tag[0] == "h" and tag[1] in "123456":
            text = self.inline_children(node).strip()
            return f"{'#' * int(tag[1])} {text}" if text else ""
        if tag in {"ul", "ol"}:
            return self.list(node, depth, ordered=tag == "ol")
        if tag == "blockquote":
            inner = self.blocks(node, depth)
            return "\n".join(f"> {line}" if line else ">" for line in inner.split("\n"))
        if tag == "pre":
            code = "".join(_raw(node)).strip("\n")
            return f"```\n{code}\n```"
        if tag == "table":
            return self.table(node)
        if tag == "hr":
            return "---"
        if tag in {"iframe", "video", "audio", "embed", "object"}:
            return self.media(node)
        return None

    def list(self, node: _Node, depth: int, *, ordered: bool) -> str:
        lines: list[str] = []
        number = 0
        for item in node.children:
            if not isinstance(item, _Node) or item.tag != "li":
                continue
            number += 1
            marker = f"{number}. " if ordered else "- "
            body = self.blocks(item, depth + 1) or ""
            pad = " " * len(marker)
            first, *rest = body.split("\n") if body else [""]
            lines.append(marker + first)
            lines.extend(pad + line if line else "" for line in rest)
        return "\n".join(lines)

    def table(self, node: _Node) -> str:
        rows: list[list[str]] = []
        for row in _find_all(node, "tr"):
            cells = [
                self.inline_children(cell)
                .strip()
                .replace("|", "\\|")
                .replace("\n", " ")
                for cell in row.children
                if isinstance(cell, _Node) and cell.tag in {"td", "th"}
            ]
            if cells:
                rows.append(cells)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(lines)

    def media(self, node: _Node) -> str:
        sources = [node.attrs.get("src") or node.attrs.get("data", "")]
        sources += [
            s.attrs.get("src", "") for s in _find_all(node, "source") if s.attrs
        ]
        out: list[str] = []
        for src in filter(None, sources):
            if node.tag == "iframe" and _VIDEO_HOSTS.search(src):
                self.videos.append(_absolute_video(src))
                continue
            url = self.rewrite(src, "media")
            if url:
                label = node.attrs.get("title") or src.rsplit("/", 1)[-1] or url
                out.append(f"[{_escape(label)}]({url})")
        return "\n\n".join(out)

    # - - - inline - - -

    def inline_children(self, node: _Node) -> str:
        return "".join(
            _text(c) if isinstance(c, str) else self.inline(c) for c in node.children
        )

    def inline(self, node: _Node) -> str:  # noqa: C901 - a dispatch
        tag = node.tag
        if tag == "title":
            self.title = _plain(node)
            return ""
        if tag in _DROP:
            return ""
        if tag == "br":
            return "  \n"
        if tag == "math":
            return _math(node)
        inner = self.inline_children(node)
        if tag in {"strong", "b"}:
            return _wrap(inner, "**")
        if tag in {"em", "i"}:
            return _wrap(inner, "*")
        if tag in {"code", "kbd", "samp", "tt"}:
            code = "".join(_raw(node))
            return f"`{code}`" if code.strip() else ""
        if tag == "img":
            src = node.attrs.get("src", "")
            url = self.rewrite(src, "image") if src else None
            alt = node.attrs.get("alt", "").replace("]", " ").replace("[", " ")
            return f"![{alt.strip()}]({url})" if url else alt
        if tag == "a":
            href = node.attrs.get("href", "").strip()
            label = inner.strip()
            if not href or href.startswith(("#", "javascript:")):
                return inner
            url = self.rewrite(href, "link")
            if not url:
                return inner
            return f"[{label or _escape(url)}]({url})"
        if tag in {"iframe", "video", "audio", "embed", "object"}:
            return self.media(node)
        block = self.block(node, 0)
        return block if block is not None else inner


def html_to_markdown(source: str, rewrite: UrlRewriter) -> HtmlConversion:
    """Convert an HTML document or fragment to step markdown."""
    builder = _TreeBuilder()
    builder.feed(source)
    builder.close()
    renderer = _Renderer(rewrite)
    body = next(iter(_find_all(builder.root, "body")), None)
    markdown = renderer.blocks(body or builder.root)
    if body is not None and not renderer.title:
        head = next(iter(_find_all(builder.root, "title")), None)
        renderer.title = _plain(head) if head is not None else ""
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return HtmlConversion(
        markdown=markdown, title=renderer.title.strip(), videos=renderer.videos
    )


def _find_all(node: _Node, tag: str) -> list[_Node]:
    found: list[_Node] = []
    for item in node.children:
        if isinstance(item, _Node):
            if item.tag == tag:
                found.append(item)
            found.extend(_find_all(item, tag))
    return found


def _raw(node: _Node) -> list[str]:
    out: list[str] = []
    for item in node.children:
        if isinstance(item, str):
            out.append(item)
        elif item.tag == "br":
            out.append("\n")
        else:
            out.extend(_raw(item))
    return out


def _plain(node: _Node) -> str:
    return _SPACES.sub(" ", "".join(_raw(node))).strip()


def _text(data: str) -> str:
    return _escape(_SPACES.sub(" ", data))


def _escape(text: str) -> str:
    return _ESCAPE.sub(r"\\\1", text)


def _wrap(inner: str, mark: str) -> str:
    stripped = inner.strip()
    if not stripped:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()) :]
    return f"{lead}{mark}{stripped}{mark}{trail}"


def _math(node: _Node) -> str:
    for annotation in _find_all(node, "annotation"):
        if "tex" in annotation.attrs.get("encoding", "").lower():
            tex = "".join(_raw(annotation)).strip()
            if tex:
                display = node.attrs.get("display") == "block"
                return f"$${tex}$$" if display else f"${tex}$"
    return _escape(_plain(node))


def _absolute_video(src: str) -> str:
    return "https:" + src if src.startswith("//") else src


# - - - Markdown to HTML (export) - - -

_FENCE: Final = re.compile(r"^```")
_HEADING: Final = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET: Final = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
_TABLE_RULE: Final = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_IMAGE: Final = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
_LINK: Final = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD: Final = re.compile(r"\*\*(.+?)\*\*")
_ITALIC: Final = re.compile(r"(?<![\\*])\*(?!\s)(.+?)(?<!\s)\*")
_CODE: Final = re.compile(r"`([^`]+)`")
_UNESCAPE: Final = re.compile(r"\\([\\`*_\[\]|])")

UrlMapper = Callable[[str], str]


def markdown_to_html(markdown: str, url: UrlMapper) -> str:  # noqa: C901
    """Render step markdown as simple, valid HTML for a cartridge page."""
    lines = markdown.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if _FENCE.match(line):
            end = index + 1
            while end < len(lines) and not _FENCE.match(lines[end]):
                end += 1
            code = html.escape("\n".join(lines[index + 1 : end]))
            out.append(f"<pre><code>{code}</code></pre>")
            index = end + 1
            continue
        if not line.strip():
            index += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2), url)}</h{level}>")
            index += 1
            continue
        if line.strip() in {"---", "***", "___"}:
            out.append("<hr/>")
            index += 1
            continue
        if line.lstrip().startswith(">"):
            end = index
            quoted: list[str] = []
            while end < len(lines) and lines[end].lstrip().startswith(">"):
                quoted.append(lines[end].lstrip()[1:].removeprefix(" "))
                end += 1
            out.append(
                f"<blockquote>{markdown_to_html(chr(10).join(quoted), url)}</blockquote>"  # noqa: E501
            )
            index = end
            continue
        if line.lstrip().startswith("|") and index + 1 < len(lines):
            if _TABLE_RULE.match(lines[index + 1].strip()):
                index = _table(lines, index, out, url)
                continue
        if _BULLET.match(line):
            index = _list(lines, index, out, url)
            continue
        end = index
        para: list[str] = []
        while end < len(lines) and lines[end].strip() and not _starts_block(lines[end]):
            para.append(lines[end])
            end += 1
        if not para:
            para, end = [line], index + 1
        out.append(f"<p>{_paragraph(para, url)}</p>")
        index = end
    return "\n".join(out)


def _starts_block(line: str) -> bool:
    stripped = line.lstrip()
    return bool(
        _FENCE.match(line)
        or _HEADING.match(line)
        or _BULLET.match(line)
        or stripped.startswith(">")
        or stripped in {"---", "***", "___"}
    )


def _paragraph(lines: list[str], url: UrlMapper) -> str:
    parts = []
    for i, line in enumerate(lines):
        hard = line.endswith("  ") and i < len(lines) - 1
        parts.append(_inline(line.strip(), url) + ("<br/>" if hard else ""))
    return "\n".join(parts)


def _list(  # noqa: C901 - list items, continuations and nesting
    lines: list[str], start: int, out: list[str], url: UrlMapper
) -> int:
    first = _BULLET.match(lines[start])
    assert first is not None  # noqa: S101 - checked by the caller
    indent = len(first.group(1))
    ordered = first.group(2)[0].isdigit()
    items: list[list[str]] = []
    index = start
    while index < len(lines):
        line = lines[index]
        match = _BULLET.match(line)
        if match and len(match.group(1)) == indent:
            items.append([match.group(3)])
        elif line.strip() and (len(line) - len(line.lstrip())) > indent and items:
            items[-1].append(
                line[indent:].lstrip() if not _BULLET.match(line) else line
            )
        elif not line.strip() and index + 1 < len(lines):
            following = lines[index + 1]
            if not following.startswith(" " * (indent + 1)) and not (
                _BULLET.match(following)
                and len(_BULLET.match(following).group(1)) == indent  # type: ignore[union-attr]  # noqa: E501
            ):
                break
        else:
            break
        index += 1
    tag = "ol" if ordered else "ul"
    rendered = []
    for item in items:
        head, rest = item[0], item[1:]
        nested = [r for r in rest if _BULLET.match(r)]
        body = _inline(head, url)
        if nested:
            dedent = min(len(r) - len(r.lstrip()) for r in nested)
            body += markdown_to_html("\n".join(r[dedent:] for r in rest), url)
        elif rest:
            body += "<br/>" + _paragraph(rest, url)
        rendered.append(f"<li>{body}</li>")
    out.append(f"<{tag}>{''.join(rendered)}</{tag}>")
    return index


def _table(lines: list[str], start: int, out: list[str], url: UrlMapper) -> int:
    def cells(line: str) -> list[str]:
        body = line.strip().removeprefix("|").removesuffix("|")
        return [c.strip() for c in re.split(r"(?<!\\)\|", body)]

    header = cells(lines[start])
    index = start + 2
    rows: list[list[str]] = []
    while index < len(lines) and lines[index].lstrip().startswith("|"):
        rows.append(cells(lines[index]))
        index += 1
    head = "".join(f"<th>{_inline(c, url)}</th>" for c in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{_inline(c, url)}</td>" for c in row) + "</tr>"
        for row in rows
    )
    out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
    return index


def _inline(text: str, url: UrlMapper) -> str:
    codes: list[str] = []

    def keep_code(match: re.Match[str]) -> str:
        codes.append(f"<code>{html.escape(match.group(1))}</code>")
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE.sub(keep_code, text)
    escaped = html.escape(text, quote=False)

    def image(match: re.Match[str]) -> str:
        src = html.escape(url(html.unescape(match.group(2))))
        alt = html.escape(_UNESCAPE.sub(r"\1", match.group(1)))
        return f'<img src="{src}" alt="{alt}"/>'

    def link(match: re.Match[str]) -> str:
        href = html.escape(url(html.unescape(match.group(2))))
        return f'<a href="{href}">{match.group(1)}</a>'

    escaped = _IMAGE.sub(image, escaped)
    escaped = _LINK.sub(link, escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _ITALIC.sub(r"<em>\1</em>", escaped)
    escaped = _UNESCAPE.sub(r"\1", escaped)
    return re.sub("\x00(\\d+)\x00", lambda m: codes[int(m.group(1))], escaped)
