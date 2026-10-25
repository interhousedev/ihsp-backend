"""Chunking of a source text into passages (§ 3.2.3).

Rules, in order: blank lines, Markdown headings and short ALL-CAPS lines make blocks;
a passage never crosses a page or unit boundary; blocks merge greedily up to 600
characters and never exceed 1 400 (long blocks are cut at a sentence end, a line
end, a space, or hard); a passage shorter than 120 characters merges with the previous
one in the same segment unless it starts with a heading.
"""

import hashlib
import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass

from app.modules.notebooks.domain.entities import DraftPassage
from app.modules.notebooks.domain.normalizer import normalize_text
from app.modules.notebooks.domain.tokens import estimate_tokens

TARGET_CHARS = 600
MAX_CHARS = 1400
MIN_CHARS = 120
HEADING_MAX_CHARS = 200
CAPS_HEADING_MAX_CHARS = 60
CAPS_HEADING_MIN_LETTERS = 3

_MD_HEADING = re.compile(r"#{1,6}[ \t]+(\S.*?)(?:[ \t]+#+)?")
_SENTENCE_END = re.compile(r"[.!?…;][\"'»”’)\]]*(?=\s)")
_NON_SPACE = re.compile(r"\S")


@dataclass(frozen=True, slots=True)
class ChunkResult:
    """Everything the source pipeline stores after reading a text."""

    text: str
    passages: list[DraftPassage]
    content_hash: str
    word_count: int
    char_count: int
    token_estimate: int


@dataclass(slots=True)
class _Segment:
    """A stretch of text between two hard boundaries (one page and/or one unit)."""

    start: int
    end: int
    page: int | None
    is_unit: bool


@dataclass(slots=True)
class _Block:
    """A blank-line separated block (stripped); `heading` is set when it starts one."""

    start: int
    end: int
    heading: str | None = None


@dataclass(slots=True)
class _Draft:
    """A passage under construction."""

    start: int
    end: int
    heading: str | None
    heading_led: bool
    segment: int
    page: int | None


def _clean_offsets(offsets: Sequence[int], size: int) -> list[int]:
    """Clamp offsets to the text and make them non-decreasing (index is kept)."""
    cleaned: list[int] = []
    floor = 0
    for offset in offsets:
        floor = min(max(offset, floor), size)
        cleaned.append(floor)
    return cleaned


def _segments(
    size: int, page_starts: Sequence[int], unit_starts: Sequence[int]
) -> list[_Segment]:
    """Cut the text at every page start and unit start."""
    pages = _clean_offsets(page_starts, size)
    units = {min(max(offset, 0), size) for offset in unit_starts}
    cuts = sorted({0, size, *pages, *units})
    segments: list[_Segment] = []
    for begin, end in zip(cuts, cuts[1:], strict=False):
        number = bisect_right(pages, begin)
        segments.append(
            _Segment(begin, end, number if number else None, begin in units)
        )
    return segments


def _heading_of(stripped: str) -> str | None:
    """Return the heading text when the (stripped) line is a heading."""
    if stripped[0] == "#":
        match = _MD_HEADING.fullmatch(stripped)
        return match.group(1)[:HEADING_MAX_CHARS].rstrip() if match else None
    if (
        len(stripped) <= CAPS_HEADING_MAX_CHARS
        and stripped.isupper()
        and "\t" not in stripped
        and sum(char.isalpha() for char in stripped) >= CAPS_HEADING_MIN_LETTERS
    ):
        return stripped
    return None


def _may_be_heading(stripped: str) -> bool:
    """Cheap pre-check so that ordinary lines skip `_heading_of`."""
    return stripped[0] == "#" or stripped.isupper()


def _blocks(text: str, start: int, end: int) -> list[_Block]:
    """Split `text[start:end]` into blocks on blank lines and heading lines."""
    blocks: list[_Block] = []
    current: _Block | None = None
    pos = start
    for line in text[start:end].split("\n"):
        body = line.lstrip()
        if not body:
            current = None
        else:
            stripped = body.rstrip()
            heading = _heading_of(stripped) if _may_be_heading(stripped) else None
            first = pos + len(line) - len(body)
            if current is None or heading is not None:
                current = _Block(first, first, heading)
                blocks.append(current)
            current.end = first + len(stripped)
        pos += len(line) + 1
    return blocks


def _trim_end(text: str, start: int, end: int) -> int:
    """Return `end` moved back over trailing whitespace (never before `start`)."""
    while end > start + 1 and text[end - 1].isspace():
        end -= 1
    return end


def _cut_position(text: str, pos: int, limit: int) -> int:
    """Pick where to cut a piece that starts at `pos` and must end by `limit`.

    Preference: the last sentence end, else the last line end, else the last space,
    else `limit`. A cut that would leave fewer than 120 characters is not used.
    """
    floor = pos + MIN_CHARS
    best = -1
    for match in _SENTENCE_END.finditer(text, floor, limit + 1):
        best = match.end()
    if best > 0:
        return best
    newline = text.rfind("\n", floor, limit + 1)
    if newline != -1:
        return newline
    space = max(text.rfind(" ", floor, limit + 1), text.rfind("\t", floor, limit + 1))
    return space if space != -1 else limit


def _cut_block(
    text: str, block: _Block, heading: str | None, segment: _Segment, index: int
) -> list[_Draft]:
    """Cut a block longer than 1 400 characters into pieces."""
    drafts: list[_Draft] = []
    pos = block.start
    led = block.heading is not None
    while block.end - pos > MAX_CHARS:
        limit = min(pos + MAX_CHARS, block.end - MIN_CHARS)
        cut = _cut_position(text, pos, limit)
        stop = _trim_end(text, pos, cut)
        drafts.append(_Draft(pos, stop, heading, led, index, segment.page))
        led = False
        found = _NON_SPACE.search(text, cut, block.end)
        pos = found.start() if found else block.end
    drafts.append(_Draft(pos, block.end, heading, led, index, segment.page))
    return drafts


def _draft_segment(
    text: str, segment: _Segment, index: int, heading: str | None
) -> tuple[list[_Draft], str | None]:
    """Build the passages of one segment; return them and the heading in force."""
    target = MAX_CHARS if segment.is_unit else TARGET_CHARS
    if segment.is_unit:
        heading = None
    drafts: list[_Draft] = []
    current: _Draft | None = None
    for block in _blocks(text, segment.start, segment.end):
        if block.heading is not None:
            heading = block.heading
            if current is not None:
                drafts.append(current)
                current = None
        if (
            current is not None
            and current.end - current.start < target
            and block.end - current.start <= MAX_CHARS
        ):
            current.end = block.end
            continue
        if current is not None:
            drafts.append(current)
        pieces = _cut_block(text, block, heading, segment, index)
        drafts.extend(pieces[:-1])
        current = pieces[-1]
    if current is not None:
        drafts.append(current)
    return drafts, heading


def _merge_short(drafts: list[_Draft]) -> list[_Draft]:
    """Merge passages under 120 characters into the previous one of the segment."""
    merged: list[_Draft] = []
    for draft in drafts:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.segment == draft.segment
            and not draft.heading_led
            and draft.end - draft.start < MIN_CHARS
            and draft.end - previous.start <= MAX_CHARS
        ):
            previous.end = draft.end
        else:
            merged.append(draft)
    return merged


def chunk_text(
    text: str,
    *,
    page_starts: Sequence[int] = (),
    unit_starts: Sequence[int] = (),
) -> list[DraftPassage]:
    """Split normalised text into passages.

    Args:
        text: Normalised text.
        page_starts: ``page_starts[i]`` is the offset where page ``i + 1`` starts.
            Text before the first start has no page number.
        unit_starts: Extra hard boundaries without a page number (chat message pairs,
            groups of 10 flash cards, LMS block parts). A unit merges blocks up to
            1 400 characters so it normally stays one passage.

    Returns:
        Passages with 1-based `seq`; ``text[p.char_start:p.char_end] == p.text``.
    """
    drafts: list[_Draft] = []
    heading: str | None = None
    for index, segment in enumerate(_segments(len(text), page_starts, unit_starts)):
        part, heading = _draft_segment(text, segment, index, heading)
        drafts.extend(part)
    return [
        DraftPassage(
            seq=seq,
            text=text[draft.start : draft.end],
            char_start=draft.start,
            char_end=draft.end,
            token_estimate=estimate_tokens(draft.end - draft.start),
            page=draft.page,
            heading=draft.heading,
        )
        for seq, draft in enumerate(_merge_short(drafts), start=1)
    ]


def chunk_source(
    raw: str,
    *,
    page_starts: Sequence[int] = (),
    unit_starts: Sequence[int] = (),
) -> ChunkResult:
    """Normalise a raw text and chunk it: the one entry point of the source pipeline.

    Args:
        raw: Extracted text.
        page_starts: Page start offsets in `raw`.
        unit_starts: Unit start offsets in `raw`.

    Returns:
        The normalised text, its passages, content hash and size statistics.
    """
    marks = [*page_starts, *unit_starts]
    normalized = normalize_text(raw, marks)
    pages = normalized.marks[: len(page_starts)]
    units = normalized.marks[len(page_starts) :]
    text = normalized.text
    return ChunkResult(
        text=text,
        passages=chunk_text(text, page_starts=pages, unit_starts=units),
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        word_count=len(text.split()),
        char_count=len(text),
        token_estimate=estimate_tokens(len(text)),
    )
