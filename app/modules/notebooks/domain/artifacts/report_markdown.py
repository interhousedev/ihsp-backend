"""Markdown clean-up of generated reports (§ 3.4.1).

Raw HTML is stripped, the heading count is capped and the table of contents is built.
Fenced code blocks are never touched; inline code spans are kept as they are.
"""

import re
from dataclasses import dataclass
from typing import Any, Final

from app.shared.text import slugify

MAX_HEADINGS: Final = 30
HEADING_TEXT_MAX_CHARS: Final = 200

_HTML_TAGS: Final = (
    "a abbr address area article aside audio b base bdi bdo big blockquote body br"
    " button canvas caption center cite code col colgroup data dd del details dfn"
    " dialog div dl dt em embed fieldset figcaption figure font footer form frame"
    " frameset h1 h2 h3 h4 h5 h6 head header hr html i iframe img input ins kbd label"
    " legend li link main map mark math menu meta meter nav noscript object ol"
    " optgroup option output p param picture pre progress q rp rt ruby s samp script"
    " section select small source span strike strong style sub summary sup svg table"
    " tbody td template textarea tfoot th thead time title tr track tt u ul var video"
    " wbr"
).split()
_TAG: Final = re.compile(
    rf"""</?(?:{'|'.join(_HTML_TAGS)})\b(?:[^<>"']|"[^"]*"|'[^']*')*>""",
    re.IGNORECASE,
)
_BREAK: Final = re.compile(r"<br\s*/?>", re.IGNORECASE)
_COMMENT: Final = re.compile(r"<!--.*?-->", re.DOTALL)
_ACTIVE_BLOCK: Final = re.compile(
    r"<(script|style)\b[^<>]*>.*?</\1\s*>", re.DOTALL | re.IGNORECASE
)
_INLINE_CODE: Final = re.compile(r"(`+[^`\n]*`+)")
_FENCE: Final = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING: Final = re.compile(r"^ {0,3}(#{1,6})[ \t]+(\S.*?)(?:[ \t]+#+)?[ \t]*$")
_CITE_MARK: Final = re.compile(r"⟦[^⟧\n]*⟧")
_LINK: Final = re.compile(r"\[([^\]]*)\]\([^)]*\)")


@dataclass(frozen=True, slots=True)
class Heading:
    """One entry of the table of contents."""

    level: int
    text: str
    id: str

    def as_dict(self) -> dict[str, Any]:
        """The stored shape: ``{level, text, id}``."""
        return {"level": self.level, "text": self.text, "id": self.id}


@dataclass(frozen=True, slots=True)
class _Segment:
    text: str
    code: bool


def strip_citation_marks(markdown: str) -> str:
    """Remove ``⟦n⟧`` chips the model wrote itself; real ones are made by the server."""
    return _CITE_MARK.sub("", markdown)


def _closes_fence(line: str, marker: str) -> bool:
    body = line.strip()
    return len(body) >= len(marker) and not body.strip(marker[0])


def _opens_fence(line: str) -> str | None:
    """The fence marker of an opening line (a backtick fence has no backtick after)."""
    match = _FENCE.match(line)
    if match is None:
        return None
    marker = match.group(1)
    if marker[0] == "`" and "`" in line[match.end() :]:
        return None
    return marker


def _split(markdown: str) -> list[_Segment]:
    """Cut the text into runs of code-fence lines and ordinary lines."""
    runs: list[tuple[bool, list[str]]] = []
    marker: str | None = None
    for line in markdown.split("\n"):
        if marker is None:
            marker = _opens_fence(line)
            code = marker is not None
        else:
            code = True
            if _closes_fence(line, marker):
                marker = None
        if runs and runs[-1][0] == code:
            runs[-1][1].append(line)
        else:
            runs.append((code, [line]))
    return [_Segment("\n".join(lines), code) for code, lines in runs]


def _join(segments: list[_Segment]) -> str:
    return "\n".join(segment.text for segment in segments)


def _strip_chunk(chunk: str) -> str:
    chunk = _ACTIVE_BLOCK.sub("", _COMMENT.sub("", chunk))
    parts = _INLINE_CODE.split(chunk)
    # odd parts are inline code spans (the pattern has one group)
    return "".join(
        part if index % 2 else _TAG.sub("", _BREAK.sub(" ", part))
        for index, part in enumerate(parts)
    )


def strip_html(markdown: str) -> str:
    """Remove raw HTML (tags, comments, script and style blocks) outside code.

    A line break ``<br>`` becomes a space so that words do not run together.
    """
    return _join(
        [
            segment if segment.code else _Segment(_strip_chunk(segment.text), False)
            for segment in _split(markdown)
        ]
    )


def _cap_chunk(chunk: str, seen: int, limit: int) -> tuple[str, int]:
    lines: list[str] = []
    for line in chunk.split("\n"):
        match = _HEADING.match(line)
        if match is not None:
            seen += 1
            if seen > limit:
                line = f"**{match.group(2)}**"
        lines.append(line)
    return "\n".join(lines), seen


def cap_headings(markdown: str, limit: int = MAX_HEADINGS) -> str:
    """Turn the headings after the ``limit``-th into bold lines."""
    seen = 0
    segments: list[_Segment] = []
    for segment in _split(markdown):
        if segment.code:
            segments.append(segment)
            continue
        text, seen = _cap_chunk(segment.text, seen, limit)
        segments.append(_Segment(text, False))
    return _join(segments)


def _plain(heading: str) -> str:
    """Heading text without chips, emphasis, code marks and link targets."""
    text = _LINK.sub(r"\1", _CITE_MARK.sub("", heading))
    text = text.replace("*", "").replace("`", "")
    return " ".join(text.split())[:HEADING_TEXT_MAX_CHARS]


def _unique_id(text: str, used: set[str]) -> str:
    base = slugify(text) or "section"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def extract_headings(markdown: str) -> list[Heading]:
    """List the ATX headings outside code with unique slug ids (``-2``, ``-3``…)."""
    used: set[str] = set()
    headings: list[Heading] = []
    for segment in _split(markdown):
        if segment.code:
            continue
        for line in segment.text.split("\n"):
            match = _HEADING.match(line)
            text = _plain(match.group(2)) if match else ""
            if match and text:
                headings.append(
                    Heading(len(match.group(1)), text, _unique_id(text, used))
                )
    return headings
