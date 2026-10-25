"""NB-12, NB-13, NB-14: the citation protocol and its SSE stream (§ 3.3.5)."""

import re

from app.modules.notebooks.domain.citation_text import MARKER
from app.modules.notebooks.domain.citations import (
    CitationPiece,
    CitationProcessor,
    CitedText,
    DeltaPiece,
    ProcessedAnswer,
    StreamingAnswer,
    StreamPiece,
    process_answer,
    split_followups,
)
from app.modules.notebooks.domain.context import ContextPack
from app.modules.notebooks.domain.entities import Citation
from app.modules.notebooks.domain.enums import SourceKind
from tests.notebooks.unit.domain.pack_builder import make_pack

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

BIOLOGY = [
    "Photosynthesis turns light into chemical energy.",
    "It happens in chloroplasts.",
    "Chlorophyll absorbs red and blue light.",
]
NOTES = ["Mitochondria produce ATP.", "Ribosomes build proteins.", "The nucleus."]


@pytest.fixture
def pack() -> ContextPack:
    return make_pack([BIOLOGY, NOTES], titles=["Biology", "Notes"])


def render(raw: str, pack: ContextPack) -> str:
    return CitationProcessor(pack).render(raw).text


def stream(
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


# - - - markers - - -


def test_render_replaces_a_marker_with_a_numbered_chip(pack: ContextPack) -> None:
    result = CitationProcessor(pack).render("Plants make sugar [[S1:P1]].")

    assert isinstance(result, CitedText)
    assert result.text == "Plants make sugar ⟦1⟧."
    assert [c.n for c in result.citations] == [1]


def test_render_groups_several_labels_into_one_chip(pack: ContextPack) -> None:
    assert render("Fact [[S1:P1, S2:P3]] end", pack) == "Fact ⟦1,2⟧ end"


def test_render_accepts_whitespace_inside_the_marker(pack: ContextPack) -> None:
    assert render("Fact [[ S1:P2 ,S2:P3 ]] end", pack) == "Fact ⟦1,2⟧ end"


def test_render_accepts_whitespace_around_the_colon(pack: ContextPack) -> None:
    assert render("Fact [[S1 : P2]] end", pack) == "Fact ⟦1⟧ end"


def test_render_accepts_a_marker_split_over_two_lines(pack: ContextPack) -> None:
    assert render("Fact [[S1:P1,\nS1:P2]] end", pack) == "Fact ⟦1,2⟧ end"


def test_render_accepts_lowercase_labels(pack: ContextPack) -> None:
    assert render("Fact [[s1:p2]] end", pack) == "Fact ⟦1⟧ end"


def test_render_drops_unknown_labels_and_keeps_the_valid_ones(
    pack: ContextPack,
) -> None:
    result = CitationProcessor(pack).render("Fact [[S1:P1, S9:P9, S2:P7]] end")

    assert result.text == "Fact ⟦1⟧ end"
    assert [c.source_title for c in result.citations] == ["Biology"]


def test_render_drops_a_marker_with_only_unknown_labels_and_the_space_before_it(
    pack: ContextPack,
) -> None:
    assert render("Fact [[S9:P9]]. Next [[S1:P1]].", pack) == "Fact. Next ⟦1⟧."


def test_render_drops_every_space_and_tab_before_an_unknown_marker(
    pack: ContextPack,
) -> None:
    assert render("Fact \t  [[S9:P9]]\nNext", pack) == "Fact\nNext"


def test_render_drops_an_unknown_marker_at_the_start_of_a_line(
    pack: ContextPack,
) -> None:
    assert render("One\n[[S9:P9]]Two", pack) == "One\nTwo"


def test_render_numbers_passages_by_first_appearance(pack: ContextPack) -> None:
    result = CitationProcessor(pack).render("A [[S2:P1]] B [[S1:P3]] C [[S1:P1]]")

    assert result.text == "A ⟦1⟧ B ⟦2⟧ C ⟦3⟧"
    assert [c.snippet for c in result.citations] == [
        NOTES[0],
        BIOLOGY[2],
        BIOLOGY[0],
    ]


def test_render_gives_a_repeated_passage_the_same_number(pack: ContextPack) -> None:
    result = CitationProcessor(pack).render("A [[S1:P2]] B [[S1:P1]] C [[S1:P2]]")

    assert result.text == "A ⟦1⟧ B ⟦2⟧ C ⟦1⟧"
    assert len(result.citations) == 2


def test_render_collapses_duplicate_labels_inside_one_marker(
    pack: ContextPack,
) -> None:
    assert render("A [[S1:P1, S1:P1]]", pack) == "A ⟦1⟧"


def test_render_sorts_the_numbers_inside_a_chip(pack: ContextPack) -> None:
    assert render("A [[S1:P1]] B [[S1:P2]] C [[S1:P2, S1:P1]]", pack) == (
        "A ⟦1⟧ B ⟦2⟧ C ⟦1,2⟧"
    )


def test_render_keeps_at_most_six_labels_in_a_chip() -> None:
    pack = make_pack([[f"text {i}" for i in range(8)]])
    labels = ", ".join(f"S1:P{i}" for i in range(1, 8))

    assert render(f"A [[{labels}]]", pack) == "A ⟦1,2,3,4,5,6⟧"


def test_render_leaves_text_without_markers_alone(pack: ContextPack) -> None:
    text = "Plain **text** with [links](http://x.y) and [1] and [S1:P1]."

    assert render(text, pack) == text


def test_render_strips_surrounding_whitespace(pack: ContextPack) -> None:
    assert render("\n\n  Answer [[S1:P1]].  \n\n", pack) == "Answer ⟦1⟧."


def test_render_of_empty_text_is_empty(pack: ContextPack) -> None:
    result = CitationProcessor(pack).render("")

    assert (result.text, result.citations) == ("", [])


def test_render_keeps_cyrillic_and_uzbek_text(pack: ContextPack) -> None:
    raw = "Фотосинтез идёт в хлоропластах [[S1:P2]]. Oʻsimliklar gʻoyalari [[S2:P1]]."

    assert render(raw, pack) == (
        "Фотосинтез идёт в хлоропластах ⟦1⟧. Oʻsimliklar gʻoyalari ⟦2⟧."
    )


def test_render_drops_an_unterminated_marker_at_the_end(pack: ContextPack) -> None:
    assert render("Fact [[S1:P1]] and [[S1:P", pack) == "Fact ⟦1⟧ and"


def test_render_drops_a_lone_double_bracket_at_the_end_but_keeps_a_single(
    pack: ContextPack,
) -> None:
    assert render("See [[", pack) == "See"
    assert render("See [", pack) == "See ["


def test_render_keeps_brackets_that_are_not_markers(pack: ContextPack) -> None:
    assert render("List [[1, 2], [3, 4]] here", pack) == "List [[1, 2], [3, 4]] here"


# - - - code - - -


def test_render_leaves_a_backtick_fence_untouched(pack: ContextPack) -> None:
    raw = "Before [[S1:P1]]\n```\n[[S1:P2]]\n```\nAfter [[S1:P3]]"

    assert render(raw, pack) == "Before ⟦1⟧\n```\n[[S1:P2]]\n```\nAfter ⟦2⟧"


def test_render_leaves_a_tilde_fence_untouched(pack: ContextPack) -> None:
    raw = "~~~python\nx = '[[S1:P1]]'\n~~~\nAfter [[S1:P2]]"

    assert render(raw, pack) == "~~~python\nx = '[[S1:P1]]'\n~~~\nAfter ⟦1⟧"


def test_render_closes_a_fence_only_with_a_fence_of_the_same_kind(
    pack: ContextPack,
) -> None:
    raw = "```\n~~~\n[[S1:P1]]\n```\n[[S1:P2]]"

    assert render(raw, pack) == "```\n~~~\n[[S1:P1]]\n```\n⟦1⟧"


def test_render_closes_a_long_fence_only_with_an_equally_long_one(
    pack: ContextPack,
) -> None:
    raw = "````\n```\n[[S1:P1]]\n```\n````\n[[S1:P2]]"

    assert render(raw, pack) == "````\n```\n[[S1:P1]]\n```\n````\n⟦1⟧"


def test_render_treats_an_unterminated_fence_as_code_to_the_end(
    pack: ContextPack,
) -> None:
    assert render("```\n[[S1:P1]] never closed", pack) == "```\n[[S1:P1]] never closed"


def test_render_does_not_see_an_indented_fence(pack: ContextPack) -> None:
    assert render("Text\n    ```\n[[S1:P1]]", pack) == "Text\n    ```\n⟦1⟧"


def test_render_leaves_inline_code_untouched(pack: ContextPack) -> None:
    raw = "Use `[[S1:P1]]` literally and [[S1:P2]]"

    assert render(raw, pack) == "Use `[[S1:P1]]` literally and ⟦1⟧"


def test_render_leaves_double_backtick_inline_code_untouched(
    pack: ContextPack,
) -> None:
    raw = "Write ``a ` [[S1:P1]] b`` then [[S1:P2]]"

    assert render(raw, pack) == "Write ``a ` [[S1:P1]] b`` then ⟦1⟧"


def test_render_replaces_a_marker_after_an_unmatched_backtick(
    pack: ContextPack,
) -> None:
    assert render("A ` lone [[S1:P1]]", pack) == "A ` lone ⟦1⟧"


def test_render_does_not_number_passages_cited_only_inside_code(
    pack: ContextPack,
) -> None:
    result = CitationProcessor(pack).render("`[[S1:P1]]` and [[S1:P2]]")

    assert result.text == "`[[S1:P1]]` and ⟦1⟧"
    assert [c.n for c in result.citations] == [1]


# - - - bullets - - -


@pytest.mark.parametrize("bullet", ["-", "*", "+", "1.", "12)"])
def test_render_moves_a_marker_before_a_bullet_to_the_end_of_the_previous_line(
    pack: ContextPack, bullet: str
) -> None:
    raw = f"Intro line\n[[S1:P1]]{bullet} item one\n{bullet} item two"

    assert render(raw, pack) == f"Intro line ⟦1⟧\n{bullet} item one\n{bullet} item two"


def test_render_moves_several_markers_before_a_bullet(pack: ContextPack) -> None:
    raw = "Intro\n[[S1:P1]] [[S1:P2]]- item"

    assert render(raw, pack) == "Intro ⟦1⟧ ⟦2⟧\n- item"


def test_render_keeps_the_indent_of_the_bullet(pack: ContextPack) -> None:
    assert render("Intro\n  [[S1:P1]]- item", pack) == "Intro ⟦1⟧\n  - item"


def test_render_drops_trailing_spaces_of_the_line_a_marker_moves_to(
    pack: ContextPack,
) -> None:
    assert render("Intro line  \n[[S1:P1]]- item", pack) == "Intro line ⟦1⟧\n- item"


def test_render_keeps_a_marker_on_the_first_line_in_place(pack: ContextPack) -> None:
    assert render("[[S1:P1]]- item", pack) == "⟦1⟧- item"


def test_render_keeps_a_marker_after_a_blank_line_in_place(pack: ContextPack) -> None:
    assert render("Intro\n\n[[S1:P1]]- item", pack) == "Intro\n\n⟦1⟧- item"


def test_render_does_not_move_a_marker_that_is_not_before_a_bullet(
    pack: ContextPack,
) -> None:
    assert render("Intro\n[[S1:P1]] text", pack) == "Intro\n⟦1⟧ text"


def test_render_does_not_move_a_marker_to_a_code_fence_line(pack: ContextPack) -> None:
    raw = "```\ncode\n```\n[[S1:P1]]- item"

    assert render(raw, pack) == "```\ncode\n```\n⟦1⟧- item"


def test_render_removes_an_unknown_marker_before_a_bullet(pack: ContextPack) -> None:
    assert render("Intro\n[[S9:P9]]- item", pack) == "Intro\n- item"


def test_render_numbers_a_moved_marker_in_text_order(pack: ContextPack) -> None:
    raw = "A [[S1:P3]]\n[[S1:P1]]- item [[S1:P2]]"

    assert render(raw, pack) == "A ⟦1⟧ ⟦2⟧\n- item ⟦3⟧"


# - - - citations - - -


def test_citations_are_snapshots_of_the_cited_passages(pack: ContextPack) -> None:
    result = CitationProcessor(pack).render("Fact [[S2:P2]].")
    passage = pack.labels["S2:P2"]

    assert result.citations == [
        Citation(
            n=1,
            passage_id=passage.passage_id,
            source_id=passage.source_id,
            source_title="Notes",
            source_kind=SourceKind.FILE,
            page=2,
            snippet="Ribosomes build proteins.",
        )
    ]


def test_citation_snippet_is_one_line_and_at_most_160_characters() -> None:
    long = "First line.\nSecond   line. " + "word " * 80
    pack = make_pack([[long]])

    citation = CitationProcessor(pack).render("A [[S1:P1]]").citations[0]

    assert "\n" not in citation.snippet
    assert len(citation.snippet) == 160
    assert citation.snippet.endswith("…")
    assert citation.snippet.startswith("First line. Second line. word")


def test_citation_numbers_follow_the_list_order(pack: ContextPack) -> None:
    result = CitationProcessor(pack).render("[[S2:P3]] [[S1:P2]] [[S2:P1]]")

    assert [c.n for c in result.citations] == [1, 2, 3]
    assert [c.snippet for c in result.citations] == [NOTES[2], BIOLOGY[1], NOTES[0]]


def test_a_label_the_pack_does_not_contain_makes_no_citation(
    pack: ContextPack,
) -> None:
    result = CitationProcessor(pack).render("A [[S3:P1]] B [[S1:P4]]")

    assert result.citations == []
    assert result.text == "A B"


# - - - follow-ups - - -


def test_split_followups_reads_the_json_list() -> None:
    raw = 'Answer.\n<followups>["Why?","How?"]</followups>'

    assert split_followups(raw) == ("Answer.", ["Why?", "How?"])


def test_split_followups_is_case_insensitive_and_tolerates_whitespace() -> None:
    raw = 'Answer.\n\n<FollowUps >\n[ "a" ,\n  "b" ]\n</FOLLOWUPS >\n'

    assert split_followups(raw) == ("Answer.", ["a", "b"])


def test_split_followups_without_a_tag_returns_the_text_unchanged() -> None:
    assert split_followups("Answer.\n") == ("Answer.\n", [])


def test_split_followups_with_invalid_json_gives_no_questions_but_removes_the_tag() -> (
    None
):
    assert split_followups("Answer.<followups>[oops</followups>") == ("Answer.", [])


@pytest.mark.parametrize("payload", ['{"a": 1}', '"text"', "42", "null"])
def test_split_followups_with_a_non_list_gives_no_questions(payload: str) -> None:
    assert split_followups(f"A<followups>{payload}</followups>") == ("A", [])


def test_split_followups_handles_an_unterminated_tag() -> None:
    assert split_followups('A<followups>["x","y"]') == ("A", ["x", "y"])


def test_split_followups_handles_an_unterminated_tag_with_broken_json() -> None:
    assert split_followups('A<followups>["x","y') == ("A", [])


def test_split_followups_handles_an_opening_without_a_bracket() -> None:
    assert split_followups('A <followups ["x"]') == ("A", [])


def test_split_followups_keeps_at_most_three_questions() -> None:
    raw = 'A<followups>["1","2","3","4","5"]</followups>'

    assert split_followups(raw)[1] == ["1", "2", "3"]


def test_split_followups_cuts_questions_to_160_characters() -> None:
    raw = 'A<followups>["' + "q" * 300 + '"]</followups>'

    assert split_followups(raw)[1] == ["q" * 160]


def test_split_followups_drops_empty_and_non_string_items() -> None:
    raw = 'A<followups>["a", 1, null, "", "  ", ["x"], "b"]</followups>'

    assert split_followups(raw)[1] == ["a", "b"]


def test_split_followups_accepts_json_in_a_code_fence() -> None:
    raw = 'A<followups>\n```json\n["a"]\n```\n</followups>'

    assert split_followups(raw) == ("A", ["a"])


def test_split_followups_cuts_everything_from_the_tag_on() -> None:
    raw = 'A<followups>["a"]</followups>\nstray text'

    assert split_followups(raw) == ("A", ["a"])


# - - - process_answer - - -


def test_process_answer_returns_text_citations_and_followups(
    pack: ContextPack,
) -> None:
    raw = 'Light becomes sugar [[S1:P1]].\n<followups>["Where?"]</followups>'

    answer = process_answer(raw, pack)

    assert isinstance(answer, ProcessedAnswer)
    assert answer.text == "Light becomes sugar ⟦1⟧."
    assert [c.n for c in answer.citations] == [1]
    assert answer.followups == ["Where?"]
    assert answer.grounded is True


def test_an_answer_without_markers_is_not_grounded(pack: ContextPack) -> None:
    answer = process_answer("I think so.", pack)

    assert answer.grounded is False
    assert answer.citations == []


def test_an_answer_with_only_unknown_markers_is_not_grounded(
    pack: ContextPack,
) -> None:
    answer = process_answer("Sure [[S7:P7]].", pack)

    assert answer.text == "Sure."
    assert answer.grounded is False


def test_the_followups_tag_is_removed_even_when_the_json_is_invalid(
    pack: ContextPack,
) -> None:
    answer = process_answer("Done [[S1:P1]]<followups>nope</followups>", pack)

    assert answer.text == "Done ⟦1⟧"
    assert answer.followups == []


# - - - streaming - - -


def test_stream_emits_text_as_soon_as_it_is_safe(pack: ContextPack) -> None:
    answer = StreamingAnswer(pack)

    first = answer.feed("Hello")
    second = answer.feed(" wor")

    assert first == [DeltaPiece("Hello")]
    assert second == [DeltaPiece(" wor")]


def test_stream_holds_trailing_spaces_until_the_next_word(pack: ContextPack) -> None:
    answer = StreamingAnswer(pack)

    assert answer.feed("Hello ") == [DeltaPiece("Hello")]
    assert answer.feed("world") == [DeltaPiece(" world")]


def test_stream_never_leaks_a_partial_marker(pack: ContextPack) -> None:
    answer = StreamingAnswer(pack)

    held = answer.feed("Fact [[S1:") + answer.feed("P1") + answer.feed("]")

    assert deltas(held) == "Fact"
    assert all("[" not in p.text for p in held if isinstance(p, DeltaPiece))


def test_stream_converts_a_completed_marker(pack: ContextPack) -> None:
    answer = StreamingAnswer(pack)
    answer.feed("Fact [[S1:P1")

    pieces = answer.feed("]]. Next")

    assert deltas(pieces) == " ⟦1⟧. Next"


def test_stream_emits_the_citation_before_the_delta_that_uses_it(
    pack: ContextPack,
) -> None:
    answer = StreamingAnswer(pack)

    pieces = answer.feed("Fact [[S1:P2]].")

    assert isinstance(pieces[0], CitationPiece)
    assert pieces[0].citation.n == 1
    assert pieces[0].citation.snippet == BIOLOGY[1]
    assert pieces[1] == DeltaPiece("Fact ⟦1⟧.")


def test_stream_emits_each_citation_once(pack: ContextPack) -> None:
    pieces, final = stream("A [[S1:P1]] B [[S1:P2]] C [[S1:P1]] D [[S2:P1]]", pack, 3)

    cited = [p.citation.n for p in pieces if isinstance(p, CitationPiece)]
    assert cited == [1, 2, 3]
    assert [c.n for c in final.citations] == [1, 2, 3]


def test_stream_citation_piece_precedes_the_first_chip_in_every_chunking(
    pack: ContextPack,
) -> None:
    raw = "A [[S1:P1]] B [[S2:P2]] C [[S1:P1, S2:P2]]"

    for size in (1, 2, 5, 100):
        pieces, _ = stream(raw, pack, size)
        seen: set[int] = set()
        for piece in pieces:
            if isinstance(piece, CitationPiece):
                seen.add(piece.citation.n)
            else:
                chips = re.findall(r"⟦([\d,]+)⟧", piece.text)
                used = {int(n) for chip in chips for n in chip.split(",")}
                assert used <= seen


def test_stream_holds_back_a_possible_followups_tag(pack: ContextPack) -> None:
    answer = StreamingAnswer(pack)

    first = answer.feed("Answer.\n\n<follow")
    second = answer.feed('ups>["Why?"')
    third = answer.feed("]</followups>")

    assert deltas(first) == "Answer."
    assert second == [] and third == []
    final = answer.finish()
    assert final.text == "Answer."
    assert final.followups == ["Why?"]


def test_stream_releases_a_lookalike_of_the_followups_tag(pack: ContextPack) -> None:
    pieces, final = stream("Use <foll tags and <b>bold</b>.", pack, 4)

    assert deltas(pieces) == "Use <foll tags and <b>bold</b>."
    assert final.text == "Use <foll tags and <b>bold</b>."


def test_stream_deltas_never_contain_the_followups_tag(pack: ContextPack) -> None:
    raw = 'Fact [[S1:P1]].\n<followups>["a","b"]</followups>'

    for size in (1, 3, 7):
        pieces, final = stream(raw, pack, size)
        assert "<" not in deltas(pieces)
        assert final.followups == ["a", "b"]


def test_stream_drops_an_unterminated_marker_at_finish(pack: ContextPack) -> None:
    pieces, final = stream("Fact [[S1:P1]] and [[S1:P2", pack, 4)

    assert final.text == "Fact ⟦1⟧ and"
    assert deltas(pieces) == "Fact ⟦1⟧ and"


def test_stream_flush_releases_what_was_held_back(pack: ContextPack) -> None:
    answer = StreamingAnswer(pack)
    during = answer.feed("Done <foll")

    flushed = answer.flush()

    assert deltas(during) == "Done"
    assert deltas(flushed) == " <foll"
    assert answer.finish().text == "Done <foll"


def test_stream_finish_keeps_the_released_pieces_when_flush_was_not_called(
    pack: ContextPack,
) -> None:
    answer = StreamingAnswer(pack)
    answer.feed("Done <foll")

    answer.finish()

    assert deltas(answer.final_pieces) == " <foll"


def test_stream_ignores_chunks_after_finish(pack: ContextPack) -> None:
    answer = StreamingAnswer(pack)
    answer.feed("One")
    first = answer.finish()

    assert answer.feed(" more") == []
    assert answer.finish() == first


def test_stream_ignores_empty_chunks(pack: ContextPack) -> None:
    assert StreamingAnswer(pack).feed("") == []


def test_stream_drops_the_space_before_an_unknown_marker_across_chunks(
    pack: ContextPack,
) -> None:
    pieces, final = stream("Fact [[S9:P9]]. Done", pack, 2)

    assert deltas(pieces) == "Fact. Done"
    assert final.text == "Fact. Done"


def test_stream_keeps_a_marker_inside_a_code_fence_untouched(
    pack: ContextPack,
) -> None:
    raw = "Code:\n```\nx = [[S1:P1]]\n```\nDone [[S1:P2]]"

    pieces, final = stream(raw, pack, 1)

    assert final.text == "Code:\n```\nx = [[S1:P1]]\n```\nDone ⟦1⟧"
    assert deltas(pieces) == final.text


def test_stream_keeps_a_marker_inside_inline_code_untouched(pack: ContextPack) -> None:
    raw = "Write `[[S1:P1]]` and [[S1:P2]]"

    pieces, final = stream(raw, pack, 1)

    assert final.text == "Write `[[S1:P1]]` and ⟦1⟧"
    assert deltas(pieces) == final.text


def test_stream_moves_a_marker_before_a_bullet_like_the_finished_answer(
    pack: ContextPack,
) -> None:
    raw = "Intro line\n[[S1:P1]]- one\n[[S1:P2]]- two\n- three"

    for size in (1, 4, 100):
        pieces, final = stream(raw, pack, size)
        assert final.text == "Intro line ⟦1⟧\n- one ⟦2⟧\n- two\n- three"
        assert deltas(pieces) == final.text


def test_stream_result_equals_the_finished_answer_for_a_realistic_text(
    pack: ContextPack,
) -> None:
    raw = (
        "Photosynthesis turns light into energy [[S1:P1]] and happens in "
        "chloroplasts [[S1:P2, S2:P1]].\n\n- Chlorophyll [[S1:P3]]\n- Unknown [[S8:P8]]"
        '\n\n```py\nprint("[[S1:P1]]")\n```\n'
        '<followups>["Where?", "Why?"]</followups>'
    )
    expected = process_answer(raw, pack)

    for size in (1, 2, 3, 5, 8, 13, 1000):
        pieces, final = stream(raw, pack, size)
        assert final == expected
        assert deltas(pieces) == expected.text


# - - - streaming equals the finished answer (property) - - -

ATOMS = [
    "[[S1:P1]]",
    "[[S2:P3, S1:P2]]",
    "[[S9:P9]]",
    "[[ S1:P2 ,S2:P3 ]]",
    "[[",
    "]]",
    "[",
    "]",
    "`",
    "``",
    "```",
    "~~~",
    "\n",
    "\n\n",
    " ",
    "  ",
    "\t",
    "- ",
    "* ",
    "1. ",
    "-",
    "text",
    "Привет",
    "<followups>",
    "</followups>",
    "<follow",
    "<FOLLOWUPS>",
    '["a","b"]',
    "S1:P1",
    ",",
    "word.",
    "```python\n",
    "\n```\n",
    "  - ",
    "\n- ",
    "[[S1:P1]]- ",
    "[[S1:P1]] ",
    "[[S1",
    ":P1",
    "]]- ",
    "\n[[S2:P2]]1. ",
    "\n[[S2:P2]]",
]
answers = st.lists(st.sampled_from(ATOMS), max_size=30).map("".join)
cuts = st.lists(st.integers(min_value=0, max_value=150), max_size=30)
SLOW_OK = [HealthCheck.too_slow, HealthCheck.data_too_large]


@settings(max_examples=600, deadline=None, suppress_health_check=SLOW_OK)
@given(answers, cuts)
def test_property_streaming_equals_the_finished_answer(
    raw: str, cut_points: list[int]
) -> None:
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
    cited = [p.citation.n for p in pieces if isinstance(p, CitationPiece)]
    assert cited == [c.n for c in expected.citations]


@settings(max_examples=300, deadline=None, suppress_health_check=SLOW_OK)
@given(
    st.lists(
        st.sampled_from([a for a in ATOMS if "`" not in a and "~" not in a]),
        max_size=30,
    ).map("".join),
    cuts,
)
def test_property_no_complete_marker_survives_outside_code(
    raw: str, cut_points: list[int]
) -> None:
    pack = make_pack([BIOLOGY, NOTES])
    answer = StreamingAnswer(pack)
    pieces: list[StreamPiece] = []
    previous = 0
    for cut in [*sorted({c for c in cut_points if c <= len(raw)}), len(raw)]:
        pieces += answer.feed(raw[previous:cut])
        previous = cut
    pieces += answer.flush()

    assert MARKER.search(deltas(pieces)) is None
    assert MARKER.search(answer.finish().text) is None


@settings(max_examples=300, deadline=None, suppress_health_check=SLOW_OK)
@given(answers)
def test_property_numbers_in_the_text_match_the_citations(raw: str) -> None:
    pack = make_pack([BIOLOGY, NOTES])

    answer = process_answer(raw, pack)

    used = {
        int(n)
        for chip in re.findall(r"⟦([\d,]+)⟧", answer.text)
        for n in chip.split(",")
    }
    assert used <= {c.n for c in answer.citations}
    assert [c.n for c in answer.citations] == list(range(1, len(answer.citations) + 1))
    assert answer.grounded == bool(answer.citations)
    assert len(answer.followups) <= 3
