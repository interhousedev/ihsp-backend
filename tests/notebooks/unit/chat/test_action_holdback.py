"""NB-6, NB-8: the stream holds back `<action` like `<followups` (§ 3.3.5)."""

from app.modules.notebooks.domain.citations import (
    CitationPiece,
    DeltaPiece,
    ProcessedAnswer,
    StreamingAnswer,
    StreamPiece,
    process_answer,
)
from app.modules.notebooks.domain.context import ContextPack
from tests.notebooks.unit.domain.pack_builder import make_pack

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

BIOLOGY = [
    "Photosynthesis turns light into chemical energy.",
    "It happens in chloroplasts.",
]
NOTES = ["Mitochondria produce ATP.", "Ribosomes build proteins."]
RAW = (
    'Fact [[S1:P1]].\n<action>{"kind": "quiz", "options": {}}</action>\n'
    '<followups>["a", "b"]</followups>'
)


@pytest.fixture
def pack() -> ContextPack:
    return make_pack([BIOLOGY, NOTES], titles=["Biology", "Notes"])


def run(
    raw: str, pack: ContextPack, size: int
) -> tuple[list[StreamPiece], ProcessedAnswer]:
    """Feed `raw` in chunks of `size`, flush and finish."""
    answer = StreamingAnswer(pack)
    pieces: list[StreamPiece] = []
    for start in range(0, len(raw), size):
        pieces += answer.feed(raw[start : start + size])
    pieces += answer.flush()
    return pieces, answer.finish()


def deltas(pieces: list[StreamPiece]) -> str:
    return "".join(p.text for p in pieces if isinstance(p, DeltaPiece))


def test_a_possible_action_tag_is_held_back_across_chunks(pack: ContextPack) -> None:
    """NB-8: `<act` waits; once it is a tag nothing more is shown."""
    answer = StreamingAnswer(pack)

    first = answer.feed("Done.\n<act")
    second = answer.feed('ion>{"kind": "quiz"}</act')
    third = answer.feed('ion>\n<followups>["a"]</followups>')

    assert deltas(first) == "Done."
    assert second == [] and third == []
    final = answer.finish()
    assert final.text == "Done."
    assert final.followups == ["a"]


@pytest.mark.parametrize("size", [1, 2, 3, 5, 8, 13, 1000])
def test_no_delta_shows_the_action_tag_in_any_chunking(
    pack: ContextPack, size: int
) -> None:
    """NB-8: the answer has the same text as without the tag."""
    pieces, final = run(RAW, pack, size)

    assert "<" not in deltas(pieces)
    assert final == process_answer(RAW, pack)
    assert final.text == "Fact ⟦1⟧." and final.followups == ["a", "b"]
    assert [p.citation.n for p in pieces if isinstance(p, CitationPiece)] == [1]


def test_followups_are_read_when_the_action_comes_first(pack: ContextPack) -> None:
    """NB-8: the tail starts at the action, the follow-ups still count."""
    _, final = run(RAW, pack, 4)

    assert final.followups == ["a", "b"]


def test_followups_are_read_when_the_action_comes_last(pack: ContextPack) -> None:
    """NB-8: either order works."""
    raw = 'Fact.\n<followups>["a"]</followups>\n<action>{"kind": "quiz"}</action>'

    pieces, final = run(raw, pack, 3)

    assert final.followups == ["a"] and final.text == "Fact."
    assert deltas(pieces).rstrip() == "Fact."


def test_a_lookalike_of_the_action_tag_is_released(pack: ContextPack) -> None:
    """NB-8: `<act` and `<a href>` are ordinary text."""
    raw = "Use <act and <a href> here."

    pieces, final = run(raw, pack, 3)

    assert deltas(pieces) == raw
    assert final.text == raw


ATOMS = [
    "Fact [[S1:P1]]. ",
    "text ",
    "\n",
    "\n\n",
    "- ",
    "`",
    "```",
    "[[",
    "]]",
    "<",
    "<a",
    "<act",
    "<action",
    "<action>",
    "</action>",
    '{"kind": "quiz"}',
    "<followups>",
    "</followups>",
    "<foll",
    '["a"]',
    "Привет",
]
answers = st.lists(st.sampled_from(ATOMS), max_size=30).map("".join)
cuts = st.lists(st.integers(min_value=0, max_value=150), max_size=30)


@settings(
    max_examples=400,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
@given(answers, cuts)
def test_property_streaming_equals_the_finished_answer_with_action_tags(
    raw: str, cut_points: list[int]
) -> None:
    """NB-8: any chunking gives the finished answer and shows no action tag."""
    pack = make_pack([BIOLOGY, NOTES])
    expected = process_answer(raw, pack)
    answer = StreamingAnswer(pack)
    pieces: list[StreamPiece] = []
    previous = 0
    for cut in [*sorted({c for c in cut_points if c <= len(raw)}), len(raw)]:
        pieces += answer.feed(raw[previous:cut])
        previous = cut
    pieces += answer.flush()
    final = answer.finish()

    assert final == expected
    assert deltas(pieces).rstrip() == expected.text
    assert "<action" not in deltas(pieces).lower()
