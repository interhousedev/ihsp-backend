"""The ``<sources>`` block of the context message (§ 3.3.3).

One format for chat and Studio. The output is deterministic: for the same pack it is
byte-identical, because the block is the provider's cache prefix.
"""

import re
from collections.abc import Sequence

from app.modules.notebooks.domain.context import ContextPack, PackSource

DEFAULT_TITLE = "Untitled"

_TITLE_FORBIDDEN = re.compile(r"[\"<>&]")
_WHITESPACE = re.compile(r"\s+")
# A line that could close or open the block, or fake a passage label.
_TAG_LINE = re.compile(r"^([ \t]*)<(?=/?(?:sources?|guide)\b)", re.MULTILINE | re.I)
_TAG_ANYWHERE = re.compile(r"<(?=/?(?:sources?|guide)\b)", re.I)
_LABEL_LINE = re.compile(r"^([ \t]*)\[(?=S\d+:P\d+\])", re.MULTILINE)


def clean_title(title: str) -> str:
    """Return a title that is safe inside ``title="..."``."""
    flat = _WHITESPACE.sub(" ", _TITLE_FORBIDDEN.sub("", title)).strip()
    return flat or DEFAULT_TITLE


def escape_passage(text: str) -> str:
    """Neutralise lines that look like block tags or passage labels.

    ``</source>`` becomes ``< /source>`` and a line starting with ``[S1:P2]`` gets a
    space after the bracket, so a source cannot close the block or fake a citation
    target.
    """
    return _LABEL_LINE.sub(r"\1[ ", _TAG_LINE.sub(r"\1< ", text))


def _render_source(source: PackSource) -> str:
    """Render one ``<source>`` element."""
    head = (
        f'<source id="S{source.n}" title="{clean_title(source.title)}" '
        f'kind="{source.kind.value}">'
    )
    lines = [head]
    if source.guide_summary:
        flat = _WHITESPACE.sub(" ", source.guide_summary).strip()
        guide = _TAG_ANYWHERE.sub("< ", flat)
        lines.append(f"<guide>{guide}</guide>")
    blocks = [f"[{p.label}] {escape_passage(p.text)}" for p in source.passages]
    if blocks:
        lines.append("\n\n".join(blocks))
    lines.append("</source>")
    return "\n".join(lines)


def render_sources_block(pack: ContextPack) -> str:
    """Render the pack as the ``<sources>`` block.

    Each source is ``<source id="S1" title="..." kind="...">`` with an optional
    ``<guide>`` line (retrieval mode) and its passages as ``[S1:P2] text`` blocks
    separated by blank lines. Titles lose ``"<>&`` and line breaks.

    Args:
        pack: The context pack of the request.

    Returns:
        The block, without a trailing newline.
    """
    body = "\n".join(_render_source(source) for source in pack.sources)
    return f"<sources>\n{body}\n</sources>" if body else "<sources>\n</sources>"


def anchor_note(labels: Sequence[str], text: str | None) -> str:
    """Return the note added to the question when the student clicked a topic.

    Args:
        labels: Labels of the anchored passages in this request (``S1:P3``).
        text: The text the student selected, if any.

    Returns:
        "The student clicked on this topic: ..." and/or "Focus on passages S1:P3,
        S1:P4" on separate lines; empty when there is nothing to say.
    """
    lines: list[str] = []
    flat = _WHITESPACE.sub(" ", text or "").strip()
    if flat:
        lines.append(f"The student clicked on this topic: {flat}")
    if labels:
        lines.append("Focus on passages " + ", ".join(labels))
    return "\n".join(lines)
