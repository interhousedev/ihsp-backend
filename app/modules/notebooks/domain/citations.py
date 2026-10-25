"""Citation protocol (§ 3.3.5): markers in the model's answer become numbered chips.

The model writes ``[[S1:P2, S2:P3]]`` after a claim. The server drops labels that are
not in the request's context pack, numbers the remaining passages by first appearance,
replaces each marker with ``⟦1,2⟧`` and builds ``Citation`` snapshots. The same engine
serves the finished answer (`CitationProcessor`, `process_answer`) and the SSE stream
(`StreamingAnswer`), so both give the same text and citations.
"""

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.notebooks.domain.artifacts.refs import snippet_of
from app.modules.notebooks.domain.citation_text import (
    FENCE_CLOSE,
    FENCE_OPEN,
    MARKER,
    MAX_LABELS,
    StartState,
    format_numbers,
    marker_labels,
    open_marker,
    render_text,
    safe_text,
    split_movable,
    start_state,
)
from app.modules.notebooks.domain.context import ContextPack, PackPassage
from app.modules.notebooks.domain.entities import Citation
from app.modules.notebooks.domain.enums import SourceKind

MAX_FOLLOWUPS = 3
FOLLOWUP_MAX_CHARS = 160

_FOLLOWUPS_TAG = re.compile(r"<followups", re.IGNORECASE)
# The hidden tail of an answer starts at the first of these tags.
_TAIL_TAG = re.compile(r"<(?:followups|action)", re.IGNORECASE)
_FOLLOWUPS_BODY = re.compile(
    r"<followups\s*>(.*?)(?:</followups\s*>|\Z)", re.IGNORECASE | re.DOTALL
)
_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class CitedText:
    """An answer with numbered markers and the citations they refer to."""

    text: str
    citations: list[Citation]


@dataclass(frozen=True, slots=True)
class ProcessedAnswer:
    """A finished model answer: text, citations, follow-up questions, grounding."""

    text: str
    citations: list[Citation]
    followups: list[str]
    grounded: bool


@dataclass(frozen=True, slots=True)
class DeltaPiece:
    """Text that can be shown at once."""

    text: str


@dataclass(frozen=True, slots=True)
class CitationPiece:
    """A newly numbered citation; arrives before the delta that uses it."""

    citation: Citation


StreamPiece = DeltaPiece | CitationPiece


def _parse_followups(tail: str) -> list[str]:
    """Read the JSON list of a ``<followups>`` tag; any problem gives ``[]``."""
    match = _FOLLOWUPS_BODY.match(tail)
    if match is None:
        return []
    payload = _JSON_FENCE.sub("", match.group(1).strip())
    try:
        data = json.loads(payload)
    except (ValueError, RecursionError):
        return []
    if not isinstance(data, list):
        return []
    questions: list[str] = []
    for item in data:
        flat = " ".join(item.split()) if isinstance(item, str) else ""
        if flat:
            questions.append(flat[:FOLLOWUP_MAX_CHARS].rstrip())
        if len(questions) == MAX_FOLLOWUPS:
            break
    return questions


def _tail_followups(tail: str) -> list[str]:
    """Read the follow-ups of a hidden tail, which may start with an ``<action``."""
    match = _FOLLOWUPS_TAG.search(tail)
    return _parse_followups(tail[match.start() :]) if match else []


def split_followups(raw: str) -> tuple[str, list[str]]:
    """Cut the trailing ``<followups>["a","b"]</followups>`` tag off an answer.

    The tag is removed in every case (also when unterminated); invalid JSON, a
    non-list or a missing tag give no follow-ups. At most 3 questions of at most 160
    characters are kept.

    Args:
        raw: The raw answer.

    Returns:
        The answer without the tag (trailing whitespace removed when a tag was cut)
        and the follow-up questions.
    """
    match = _FOLLOWUPS_TAG.search(raw)
    if match is None:
        return raw, []
    return raw[: match.start()].rstrip(), _parse_followups(raw[match.start() :])


class _Numbering:
    """Numbers passages by first appearance and builds their citation snapshots."""

    def __init__(
        self,
        pack: ContextPack,
        numbers: dict[UUID, int] | None = None,
        citations: list[Citation] | None = None,
    ) -> None:
        """Start empty, or continue from a copy of earlier state."""
        self._pack = pack
        self._numbers = numbers if numbers is not None else {}
        self.citations: list[Citation] = citations if citations is not None else []

    def fork(self) -> "_Numbering":
        """Return an independent copy (a line is rendered on a copy, then kept)."""
        return _Numbering(self._pack, dict(self._numbers), list(self.citations))

    def resolve(self, labels: Iterable[str]) -> list[int]:
        """Return the numbers of the valid labels, numbering new passages."""
        numbers: list[int] = []
        for label in labels:
            passage = self._pack.labels.get(label)
            if passage is None:
                continue
            number = self._numbers.get(passage.passage_id)
            if number is None:
                number = len(self.citations) + 1
                self._numbers[passage.passage_id] = number
                self.citations.append(self._snapshot(number, passage))
            if number not in numbers:
                numbers.append(number)
        return numbers

    def _snapshot(self, number: int, passage: PackPassage) -> Citation:
        """Build the stored citation of a passage."""
        title, kind = self._source_meta(passage.source_id)
        return Citation(
            n=number,
            passage_id=passage.passage_id,
            source_id=passage.source_id,
            source_title=title,
            source_kind=kind,
            page=passage.page,
            snippet=snippet_of(passage.text),
        )

    def _source_meta(self, source_id: UUID) -> tuple[str, SourceKind]:
        """Return the title and kind of a source of the pack."""
        if source_id in self._pack.titles:
            return self._pack.titles[source_id]
        for source in self._pack.sources:
            if source.source_id == source_id:
                return source.title, source.kind
        raise KeyError(source_id)


@dataclass(slots=True)
class _Rendered:
    """One line rendered: markers to move to the previous line, and the line."""

    moved: str
    body: str
    numbering: _Numbering


@dataclass(slots=True)
class _State:
    """Mutable state of the engine between lines."""

    buf: str = ""
    tail: str | None = None
    fence: tuple[str, int] | None = None
    pending: str = ""  # whitespace held back between the last released text and now
    released: bool = False  # some visible text went out
    prev_movable: bool = False  # the last line is plain text that can take a marker
    head_done: bool = False  # the current line started to go out
    line_mode: StartState | None = None  # decided at the start of each line
    line_out: int = 0  # characters of the current line's rendering already out
    cits_sent: int = 0
    finished: bool = False
    parts: list[str] = field(default_factory=list)
    queue: list[StreamPiece] = field(default_factory=list)


class _Engine:
    """Turns raw answer text, fed in any chunking, into text, citations and pieces."""

    def __init__(self, pack: ContextPack) -> None:
        """Create an engine for one answer."""
        self._numbering = _Numbering(pack)
        self._s = _State()
        self.final_pieces: list[StreamPiece] = []

    # - - - public - - -

    def feed(self, chunk: str) -> list[StreamPiece]:
        """Add text and return the pieces that are safe to show."""
        state = self._s
        if state.finished or not chunk:
            return []
        if state.tail is not None:
            state.tail += chunk
        else:
            state.buf += chunk
            self._drain(final=False)
        return self._take()

    def finish(self) -> ProcessedAnswer:
        """Flush what is held back and return the processed answer."""
        state = self._s
        if not state.finished:
            self._drain(final=True)
            state.finished = True
            self.final_pieces = self._take()
        citations = list(self._numbering.citations)
        followups = _tail_followups(state.tail) if state.tail is not None else []
        return ProcessedAnswer(
            text="".join(state.parts).rstrip(),
            citations=citations,
            followups=followups,
            grounded=bool(citations),
        )

    # - - - lines - - -

    def _drain(self, *, final: bool) -> None:
        """Process every complete line, then the unfinished one."""
        state = self._s
        tag = _TAIL_TAG.search(state.buf)
        if tag is not None:
            state.tail = state.buf[tag.start() :]
            state.buf = state.buf[: tag.start()]
            final = True
        while (end := self._line_end()) >= 0:
            line, state.buf = state.buf[:end], state.buf[end + 1 :]
            self._complete_line(line)
        if state.buf:
            self._partial(final=final)
        if final:
            state.buf = ""

    def _line_end(self) -> int:
        """Return the index of the newline that ends the first line, or -1.

        A newline inside an unfinished ``[[...`` marker does not end the line (except
        in code, where `[[1, 2` is ordinary text).
        """
        buf = self._s.buf
        extend = not self._is_verbatim(buf)
        start = 0
        while (index := buf.find("\n", start)) >= 0:
            if not extend or open_marker(buf[:index]) is None:
                return index
            start = index + 1
        return -1

    def _complete_line(self, line: str) -> None:
        """Render a line that ended with a newline and keep it."""
        state = self._s
        verbatim = self._is_verbatim(line)
        result = self._render(line, final=True)
        if result is not None:
            self._emit(result)
            self._numbering = result.numbering
        trailing = line[len(line.rstrip(" \t")) :]
        state.pending += trailing + "\n"
        state.prev_movable = state.head_done and not verbatim
        self._update_fence(line)
        state.head_done = False
        state.line_mode = None
        state.line_out = 0

    def _partial(self, *, final: bool) -> None:
        """Release the safe part of the unfinished last line."""
        result = self._render(self._s.buf, final=final)
        if result is None:
            return
        self._emit(result)
        if final:
            self._numbering = result.numbering

    # - - - rendering - - -

    def _is_verbatim(self, line: str) -> bool:
        """True for code fence lines and lines inside a fence."""
        return self._s.fence is not None or FENCE_OPEN.match(line) is not None

    def _can_move(self) -> bool:
        """True when a marker can be appended to the previous line."""
        state = self._s
        return state.released and state.prev_movable and state.pending.count("\n") == 1

    def _render(self, text: str, *, final: bool) -> _Rendered | None:
        """Render a line (or its safe part); None while its start is undecided."""
        scratch = self._numbering.fork()
        verbatim = self._is_verbatim(text)
        safe = safe_text(text, final=final, verbatim=verbatim)
        if verbatim:
            return _Rendered("", safe, scratch)
        mode = self._line_mode(text, final=final)
        if mode == "undecided":
            return None
        if mode == "move":
            return self._render_move(text, safe, scratch)
        return _Rendered("", render_text(safe, scratch.resolve), scratch)

    def _line_mode(self, text: str, *, final: bool) -> StartState:
        """Decide once per line whether its leading markers move to the line above."""
        state = self._s
        if state.line_mode is None:
            mode: StartState = "normal"
            if self._can_move():
                mode = start_state(text, final=final)
            if mode == "undecided":
                return mode
            state.line_mode = mode
        return state.line_mode

    @staticmethod
    def _render_move(text: str, safe: str, scratch: _Numbering) -> _Rendered:
        """Render a line that starts with markers before a bullet."""
        parts = split_movable(text)
        if parts is None:  # not reachable: `start_state` just matched it
            return _Rendered("", safe, scratch)
        indent, run, end = parts
        chips = [
            scratch.resolve(marker_labels(match.group(0))[:MAX_LABELS])
            for match in MARKER.finditer(run)
        ]
        moved = " ".join(format_numbers(numbers) for numbers in chips if numbers)
        body = indent + render_text(safe[end:], scratch.resolve)
        return _Rendered(moved, body, scratch)

    def _update_fence(self, line: str) -> None:
        """Open or close a fenced code block after a complete line."""
        state = self._s
        if state.fence is None:
            match = FENCE_OPEN.match(line)
            if match:
                state.fence = (match.group(1)[0], len(match.group(1)))
            return
        match = FENCE_CLOSE.fullmatch(line)
        if match and match.group(1)[0] == state.fence[0]:
            if len(match.group(1)) >= state.fence[1]:
                state.fence = None

    # - - - output - - -

    def _emit(self, result: _Rendered) -> None:
        """Release the new part of a rendered line (citations go first)."""
        state = self._s
        new = result.body[state.line_out :]
        if not (new or result.moved):
            return
        for citation in result.numbering.citations[state.cits_sent :]:
            state.queue.append(CitationPiece(citation))
        state.cits_sent = len(result.numbering.citations)
        if not state.head_done:
            if result.moved:
                state.pending = state.pending.lstrip(" \t")
                self._push(" " + result.moved)
            self._push(state.pending)
            state.pending = ""
            state.head_done = True
        self._push(new)
        state.line_out = len(result.body)

    def _push(self, text: str) -> None:
        """Queue visible text; leading whitespace of the answer is dropped."""
        state = self._s
        if not state.released:
            text = text.lstrip()
        if not text:
            return
        state.released = True
        state.parts.append(text)
        if state.queue and isinstance(state.queue[-1], DeltaPiece):
            state.queue[-1] = DeltaPiece(state.queue[-1].text + text)
        else:
            state.queue.append(DeltaPiece(text))

    def _take(self) -> list[StreamPiece]:
        """Return and clear the queued pieces."""
        pieces, self._s.queue = self._s.queue, []
        return pieces


class CitationProcessor:
    """Renders the markers of a model answer against a context pack."""

    def __init__(self, pack: ContextPack) -> None:
        """Remember the pack whose labels are valid."""
        self._pack = pack

    def render(self, raw: str) -> CitedText:
        """Replace markers with ``⟦n⟧`` and build the citations.

        Labels that are not in the pack are dropped (a marker with no valid label
        disappears with the space before it); passages are numbered by first
        appearance; fenced and inline code stay untouched; a marker that stands right
        before a list bullet at the start of a line moves to the end of the previous
        line. A ``<followups>`` tag, if any, is cut off.
        """
        engine = _Engine(self._pack)
        engine.feed(raw)
        answer = engine.finish()
        return CitedText(answer.text, answer.citations)


def process_answer(raw: str, pack: ContextPack) -> ProcessedAnswer:
    """Process a finished answer: follow-ups first, then citations.

    Args:
        raw: The raw model answer.
        pack: The context pack the answer was written for.

    Returns:
        Text with ``⟦n⟧`` markers, citations, follow-ups and ``grounded`` (at least
        one valid citation).
    """
    cited = CitationProcessor(pack).render(raw)
    return ProcessedAnswer(
        text=cited.text,
        citations=cited.citations,
        followups=split_followups(raw)[1],
        grounded=bool(cited.citations),
    )


class StreamingAnswer:
    """Converts an answer chunk by chunk for SSE.

    Text goes out as soon as it is safe: a marker is held from ``[[`` to ``]]`` so a
    partial marker never leaks, as are trailing spaces, an unmatched backtick and a
    possible ``<followups`` or ``<action`` tag (the tail of the answer). A
    `CitationPiece` comes before the first delta that uses the citation.
    """

    def __init__(self, pack: ContextPack) -> None:
        """Start an empty stream for a pack."""
        self._engine = _Engine(pack)

    def feed(self, chunk: str) -> list[StreamPiece]:
        """Add a chunk of the raw answer; return the pieces that are safe to show."""
        return self._engine.feed(chunk)

    def flush(self) -> list[StreamPiece]:
        """Release what is still held back (call once after the last chunk)."""
        self._engine.finish()
        pieces, self._engine.final_pieces = self._engine.final_pieces, []
        return pieces

    def finish(self) -> ProcessedAnswer:
        """End the stream; text and citations equal `process_answer` of the raw text.

        Whatever was still held back is available in `final_pieces`, unless
        `flush` was called first.
        """
        return self._engine.finish()

    @property
    def final_pieces(self) -> list[StreamPiece]:
        """Pieces released by `finish` (held-back text, citations)."""
        return self._engine.final_pieces
