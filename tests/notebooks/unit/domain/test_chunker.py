"""NB-6, NB-7: chunking a source text into passages (§ 3.2.3)."""

import hashlib
import time
from bisect import bisect_right

from app.modules.notebooks.domain.chunker import (
    MAX_CHARS,
    MIN_CHARS,
    ChunkResult,
    chunk_source,
    chunk_text,
)
from app.modules.notebooks.domain.entities import DraftPassage
from app.modules.notebooks.domain.tokens import estimate_tokens

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

SENTENCES = " ".join(f"Sentence number {i} says something useful." for i in range(80))


def paragraph(size: int, word: str = "word") -> str:
    """A paragraph of exactly `size` characters made of one repeated word."""
    body = (word + " ") * (size // (len(word) + 1) + 1)
    body = body[:size]
    return body[:-1] + word[-1] if body.endswith(" ") else body


def squash(text: str) -> str:
    """Remove all whitespace: what must survive chunking."""
    return "".join(text.split())


def assert_slices(text: str, passages: list[DraftPassage]) -> None:
    """Every passage is the exact, stripped slice of the text it points at."""
    for passage in passages:
        assert text[passage.char_start : passage.char_end] == passage.text
        assert passage.text == passage.text.strip()
        assert passage.text


# - - - basics - - -


def test_chunk_text_returns_nothing_for_empty_text() -> None:
    assert chunk_text("") == []


def test_chunk_text_returns_nothing_for_whitespace_only_text() -> None:
    assert chunk_text(" \n\n \t ") == []


def test_chunk_text_keeps_a_single_character_as_one_passage() -> None:
    passages = chunk_text("x")

    assert [(p.seq, p.text, p.char_start, p.char_end) for p in passages] == [
        (1, "x", 0, 1)
    ]


def test_chunk_text_makes_one_passage_of_a_short_text() -> None:
    passages = chunk_text("Hello world.")

    assert len(passages) == 1
    assert passages[0].page is None
    assert passages[0].heading is None
    assert passages[0].token_estimate == estimate_tokens(12)


def test_chunk_text_strips_whitespace_around_the_passage() -> None:
    text = "\n\n  Hello world.  \n"

    passages = chunk_text(text)

    assert passages[0].text == "Hello world."
    assert passages[0].char_start == 4
    assert_slices(text, passages)


def test_chunk_text_numbers_passages_from_one() -> None:
    text = "\n\n".join(paragraph(700, f"w{i}") for i in range(4))

    passages = chunk_text(text)

    assert [p.seq for p in passages] == [1, 2, 3, 4]


def test_chunk_text_estimates_tokens_from_the_passage_length() -> None:
    text = "\n\n".join(paragraph(700, f"w{i}") for i in range(3))

    passages = chunk_text(text)

    assert [p.token_estimate for p in passages] == [
        estimate_tokens(len(p.text)) for p in passages
    ]


# - - - merging and cutting - - -


def test_blocks_merge_until_the_passage_reaches_600_characters() -> None:
    text = "\n\n".join(paragraph(400, f"w{i}") for i in range(4))

    passages = chunk_text(text)

    assert [len(p.text) for p in passages] == [802, 802]


def test_a_block_that_would_pass_1400_characters_starts_a_new_passage() -> None:
    text = paragraph(500, "a") + "\n\n" + paragraph(950, "b")

    passages = chunk_text(text)

    assert [len(p.text) for p in passages] == [500, 950]


def test_blocks_that_fit_within_1400_characters_merge() -> None:
    text = paragraph(500, "a") + "\n\n" + paragraph(800, "b")

    passages = chunk_text(text)

    assert [len(p.text) for p in passages] == [1302]


def test_a_long_block_is_cut_at_the_last_sentence_end_before_1400() -> None:
    passages = chunk_text(SENTENCES)

    assert len(passages) > 1
    assert all(len(p.text) <= MAX_CHARS for p in passages)
    assert all(p.text.endswith(".") for p in passages)
    assert squash("".join(p.text for p in passages)) == squash(SENTENCES)


def test_a_long_block_without_sentence_ends_is_cut_at_a_space() -> None:
    text = " ".join(["слово"] * 700)

    passages = chunk_text(text)

    assert len(passages) > 2
    assert all(len(p.text) <= MAX_CHARS for p in passages)
    assert all(set(p.text.split()) == {"слово"} for p in passages)


def test_a_long_block_without_spaces_is_cut_hard_at_1400() -> None:
    passages = chunk_text("x" * 3500)

    assert [len(p.text) for p in passages] == [1400, 1400, 700]


def test_the_tail_of_a_hard_cut_keeps_at_least_120_characters() -> None:
    passages = chunk_text("x" * 1450)

    assert [len(p.text) for p in passages] == [1330, 120]


def test_a_sentence_end_is_preferred_to_a_line_end() -> None:
    first = paragraph(700, "alpha") + "."
    text = first + "\n" + paragraph(600, "beta") + "\n" + paragraph(300, "gamma")

    passages = chunk_text(text)

    assert passages[0].text == first


def test_a_sentence_end_needs_whitespace_after_it() -> None:
    text = "3.14 " * 400

    passages = chunk_text(text)

    assert all(p.text.endswith("3.14") for p in passages)


def test_table_rows_are_cut_at_line_ends() -> None:
    text = "\n".join(f"item{i}\t{i * 7}\tvalue" for i in range(300))

    passages = chunk_text(text)

    assert len(passages) > 2
    assert all(p.text.startswith("item") and p.text.endswith("value") for p in passages)
    assert all(len(p.text) <= MAX_CHARS for p in passages)


def test_a_table_with_header_in_capitals_is_not_a_heading() -> None:
    text = "ID\tNAME\tAGE\n1\tAli\t20\n2\tVali\t21"

    passages = chunk_text(text)

    assert [p.heading for p in passages] == [None]


# - - - headings - - -


def test_markdown_heading_becomes_the_heading_and_stays_in_the_text() -> None:
    passages = chunk_text("# Title\n\nShort body text here.")

    assert len(passages) == 1
    assert passages[0].heading == "Title"
    assert passages[0].text.startswith("# Title")


def test_heading_applies_to_every_following_passage_until_the_next_one() -> None:
    text = "# Глава 1\n\n" + "\n\n".join(paragraph(1000, f"w{i}") for i in range(3))

    passages = chunk_text(text)

    assert len(passages) == 3
    assert {p.heading for p in passages} == {"Глава 1"}


def test_a_new_heading_starts_a_new_passage_with_its_own_heading() -> None:
    passages = chunk_text("# A\n\ntext a here\n\n# B\n\ntext b here")

    assert [p.heading for p in passages] == ["A", "B"]
    assert passages[0].text == "# A\n\ntext a here"


def test_text_before_the_first_heading_has_no_heading() -> None:
    passages = chunk_text(
        "Intro sentence of the lesson.\n\n# Part\n\nBody of the part."
    )

    assert [p.heading for p in passages] == [None, "Part"]


def test_a_heading_line_inside_a_paragraph_starts_a_new_block() -> None:
    passages = chunk_text("Intro line one.\n# Heading\nbody of it")

    assert [p.text for p in passages] == ["Intro line one.", "# Heading\nbody of it"]


def test_a_line_in_capitals_is_a_heading() -> None:
    passages = chunk_text("INTRODUCTION\n\nSome body text of the lesson.")

    assert passages[0].heading == "INTRODUCTION"


def test_a_cyrillic_line_in_capitals_is_a_heading() -> None:
    passages = chunk_text("ВВЕДЕНИЕ\n\nТекст первого раздела урока.")

    assert passages[0].heading == "ВВЕДЕНИЕ"


def test_heading_levels_one_to_six_are_headings() -> None:
    for level in range(1, 7):
        passages = chunk_text("#" * level + " Name\n\nbody text")

        assert passages[0].heading == "Name"


@pytest.mark.parametrize(
    "line",
    [
        "AB",
        "A" * 61,
        "ID\tNAME",
        "Mixed Case Title",
        "#hashtag",
        "####### too deep",
        "#",
    ],
)
def test_lines_that_only_look_like_headings_are_not_headings(line: str) -> None:
    passages = chunk_text(line + "\n\nsome body text here")

    assert [p.heading for p in passages] == [None]


def test_a_line_in_capitals_of_exactly_60_characters_is_a_heading() -> None:
    passages = chunk_text("A" * 60 + "\n\nsome body text here")

    assert passages[0].heading == "A" * 60


def test_heading_text_is_cut_to_200_characters() -> None:
    passages = chunk_text("# " + "h" * 300 + "\n\nbody")

    assert passages[0].heading == "h" * 200


def test_closing_hashes_are_not_part_of_the_heading() -> None:
    passages = chunk_text("## Name ##\n\nbody")

    assert passages[0].heading == "Name"


def test_heading_only_passage_is_not_merged_into_the_previous_one() -> None:
    text = paragraph(700, "a") + "\n\n# Last\n"

    passages = chunk_text(text)

    assert [p.heading for p in passages] == [None, "Last"]


# - - - short passages - - -


def test_a_short_passage_merges_with_the_previous_one() -> None:
    text = paragraph(700, "a") + "\n\nShort tail."

    passages = chunk_text(text)

    assert len(passages) == 1
    assert passages[0].text.endswith("Short tail.")


def test_a_short_passage_behind_a_heading_is_kept_apart() -> None:
    text = paragraph(700, "alpha") + "\n\n# H\n\nx"

    passages = chunk_text(text)

    assert [p.text[:5] for p in passages] == ["alpha", "# H\n\n"]


def test_a_short_passage_does_not_merge_when_the_result_would_pass_1400() -> None:
    text = paragraph(1395, "a") + "\n\n" + "tail " * 10

    passages = chunk_text(text)

    assert len(passages) == 2
    assert len(passages[1].text) < MIN_CHARS


# - - - pages - - -


def test_passages_get_the_page_they_start_on() -> None:
    pages = [paragraph(300, f"p{i}") for i in range(3)]
    text = "\n\n".join(pages)
    starts = [0, len(pages[0]) + 2, len(pages[0]) + len(pages[1]) + 4]

    passages = chunk_text(text, page_starts=starts)

    assert [(p.page, p.text[:2]) for p in passages] == [
        (1, "p0"),
        (2, "p1"),
        (3, "p2"),
    ]


def test_a_passage_never_crosses_a_page_boundary_inside_a_block() -> None:
    text = paragraph(500, "word")

    passages = chunk_text(text, page_starts=[0, 250])

    assert [p.page for p in passages] == [1, 2]
    assert passages[0].char_end <= 250 <= passages[1].char_start


def test_a_short_page_is_not_merged_with_the_previous_page() -> None:
    first = paragraph(700, "alpha")
    text = first + "\n\nShort page."

    passages = chunk_text(text, page_starts=[0, len(first) + 2])

    assert [(p.page, p.text[:5]) for p in passages] == [(1, "alpha"), (2, "Short")]


def test_text_before_the_first_page_start_has_no_page() -> None:
    passages = chunk_text("Cover text.\n\nPage text.", page_starts=[13])

    assert [p.page for p in passages] == [None, 1]


def test_an_empty_page_is_skipped_in_the_numbering() -> None:
    text = "First page text.\n\nThird page text."

    passages = chunk_text(text, page_starts=[0, 18, 18])

    assert [p.page for p in passages] == [1, 3]


def test_page_starts_beyond_the_text_create_no_passages() -> None:
    passages = chunk_text("Only page.", page_starts=[0, 500, 900])

    assert [(p.page, p.text) for p in passages] == [(1, "Only page.")]


def test_without_page_starts_the_page_is_none() -> None:
    passages = chunk_text("Some text.\n\n" + paragraph(900, "a"))

    assert {p.page for p in passages} == {None}


def test_heading_stays_in_force_on_the_next_page() -> None:
    text = "# Chapter\n\nPage one text.\n\nPage two text."
    second = text.index("Page two")

    passages = chunk_text(text, page_starts=[0, second])

    assert [(p.page, p.heading) for p in passages] == [(1, "Chapter"), (2, "Chapter")]


# - - - units - - -


def test_units_are_never_merged_even_when_short() -> None:
    text = "One.\n\nTwo.\n\nThree."

    passages = chunk_text(text, unit_starts=[0, 6, 12])

    assert [p.text for p in passages] == ["One.", "Two.", "Three."]
    assert {p.page for p in passages} == {None}


def test_a_unit_keeps_its_blocks_in_one_passage_up_to_1400_characters() -> None:
    text = "\n\n".join(paragraph(300, f"w{i}") for i in range(3))

    as_unit = chunk_text(text, unit_starts=[0])
    as_page = chunk_text(text)

    assert len(as_unit) == 1
    assert len(as_page) == 2


def test_a_unit_longer_than_1400_characters_is_cut_inside_the_unit() -> None:
    first = paragraph(100, "a")
    text = first + "\n\n" + paragraph(3000, "b")

    passages = chunk_text(text, unit_starts=[len(first) + 2])

    assert len(passages) >= 4
    assert passages[0].text == first
    assert all(len(p.text) <= MAX_CHARS for p in passages)


def test_a_unit_can_start_in_the_middle_of_a_line() -> None:
    passages = chunk_text("first part second part", unit_starts=[11])

    assert [p.text for p in passages] == ["first part", "second part"]


def test_a_unit_start_resets_the_heading() -> None:
    text = "# Heading\n\nbody\n\nnext unit text"

    passages = chunk_text(text, unit_starts=[text.index("next")])

    assert [p.heading for p in passages] == ["Heading", None]


def test_pages_and_units_combine() -> None:
    text = "Page one A.\n\nPage one B.\n\nPage two A."
    pages = [0, text.index("Page two")]
    units = [text.index("Page one B")]

    passages = chunk_text(text, page_starts=pages, unit_starts=units)

    assert [(p.page, p.text) for p in passages] == [
        (1, "Page one A."),
        (1, "Page one B."),
        (2, "Page two A."),
    ]


# - - - languages and tables - - -


def test_russian_text_is_cut_at_sentence_ends_and_slices_back() -> None:
    text = " ".join(f"Это предложение номер {i} про фотосинтез." for i in range(60))

    passages = chunk_text(text)

    assert len(passages) > 1
    assert all(p.text.endswith("фотосинтез.") for p in passages)
    assert_slices(text, passages)


def test_uzbek_apostrophes_survive_chunking() -> None:
    text = " ".join(f"Oʻzbekiston gʻoyalari ʼayn {i} haqida." for i in range(60))

    result = chunk_source(text)

    assert "".join(result.text.split()) == "".join(text.split())
    assert any("oʻ" in p.text.lower() and "gʻ" in p.text for p in result.passages)
    assert_slices(result.text, result.passages)


def test_a_table_heavy_text_is_chunked_on_whole_rows() -> None:
    rows = [f"{i}\tИмя {i}\t{i % 7}\t{i * 3.5}" for i in range(500)]
    text = "\n".join(rows)

    result = chunk_source(text)

    assert all(len(p.text) <= MAX_CHARS for p in result.passages)
    cells = "\n".join(p.text for p in result.passages)
    assert cells.split("\n") == rows
    assert_slices(result.text, result.passages)


# - - - chunk_source - - -


def test_chunk_source_of_empty_text_is_empty() -> None:
    result = chunk_source("")

    assert result == ChunkResult(
        text="",
        passages=[],
        content_hash=hashlib.sha256(b"").hexdigest(),
        word_count=0,
        char_count=0,
        token_estimate=0,
    )


def test_chunk_source_of_one_character() -> None:
    result = chunk_source("я")

    assert [p.text for p in result.passages] == ["я"]
    assert (result.word_count, result.char_count, result.token_estimate) == (1, 1, 1)


def test_chunk_source_reports_sizes_and_hash_of_the_normalized_text() -> None:
    result = chunk_source("one two\r\n\r\n\r\n\r\nthree  \n")

    assert result.text == "one two\n\nthree\n"
    assert result.word_count == 3
    assert result.char_count == len(result.text)
    assert result.token_estimate == estimate_tokens(len(result.text))
    assert result.content_hash == hashlib.sha256(result.text.encode()).hexdigest()


def test_chunk_source_hash_changes_with_the_text() -> None:
    assert chunk_source("a b").content_hash != chunk_source("a c").content_hash
    assert chunk_source("a\nb").content_hash == chunk_source("a\r\nb").content_hash


def test_chunk_source_maps_page_starts_through_normalization() -> None:
    raw = "Page one text.\r\n\r\n\r\n\r\nPage two text."
    second = raw.index("Page two")

    result = chunk_source(raw, page_starts=[0, second])

    assert [(p.page, p.text) for p in result.passages] == [
        (1, "Page one text."),
        (2, "Page two text."),
    ]
    assert_slices(result.text, result.passages)


def test_chunk_source_maps_unit_starts_through_normalization() -> None:
    raw = "Question​ one?\r\nAnswer one.\r\n\r\nQuestion two?"
    second = raw.index("Question two")

    result = chunk_source(raw, unit_starts=[0, second])

    assert [p.text for p in result.passages] == [
        "Question one?\nAnswer one.",
        "Question two?",
    ]


@pytest.mark.slow
def test_chunk_source_handles_600000_characters_in_under_two_seconds() -> None:
    block = (
        "\n\n".join(
            f"Абзац {i}. Это предложение про фотосинтез. Oʻzbekiston gʻoyalari. " * 4
            for i in range(10)
        )
        + "\n\n"
    )
    raw = block * (600_000 // len(block))
    page_starts = list(range(0, len(raw), 3000))

    started = time.perf_counter()
    result = chunk_source(raw, page_starts=page_starts)
    elapsed = time.perf_counter() - started

    assert len(raw) >= 590_000
    assert elapsed < 2.0
    assert len(result.passages) > 300
    assert_slices(result.text, result.passages)


@pytest.mark.slow
def test_chunk_source_handles_600000_characters_without_any_space_quickly() -> None:
    started = time.perf_counter()
    result = chunk_source("x" * 600_000)

    assert time.perf_counter() - started < 2.0
    assert max(len(p.text) for p in result.passages) <= MAX_CHARS


# - - - properties - - -

PROSE = [
    "word",
    "Слово",
    "oʻzbek",
    "gʻoya",
    "ʼ",
    " ",
    " ",
    "\n",
    "\n\n",
    "\n\n",
    "\t",
    ". ",
    "! ",
    "? ",
    "… ",
    "; ",
    ", ",
    "x" * 40,
]
HEADINGS = ["# Heading\n", "\n## Sub\n\n", "\nCAPS TITLE\n", "\n\n# H2\n\n"]
prose_text = st.lists(st.sampled_from(PROSE), max_size=700).map("".join)
mixed_text = st.lists(st.sampled_from(PROSE + HEADINGS), max_size=700).map("".join)
SLOW_OK = [HealthCheck.too_slow, HealthCheck.data_too_large]


@settings(max_examples=150, deadline=None, suppress_health_check=SLOW_OK)
@given(mixed_text)
def test_property_passages_slice_back_to_the_text(text: str) -> None:
    passages = chunk_text(text)

    assert_slices(text, passages)
    assert [p.seq for p in passages] == list(range(1, len(passages) + 1))
    assert all(p.token_estimate == estimate_tokens(len(p.text)) for p in passages)


@settings(max_examples=150, deadline=None, suppress_health_check=SLOW_OK)
@given(mixed_text)
def test_property_passages_partition_the_text_in_order(text: str) -> None:
    passages = chunk_text(text)

    ends = [0, *(p.char_end for p in passages)]
    starts = [p.char_start for p in passages]
    assert all(start >= end for start, end in zip(starts, ends, strict=False))
    assert squash("".join(p.text for p in passages)) == squash(text)


@settings(max_examples=150, deadline=None, suppress_health_check=SLOW_OK)
@given(mixed_text)
def test_property_no_passage_is_longer_than_1400_characters(text: str) -> None:
    assert all(len(p.text) <= MAX_CHARS for p in chunk_text(text))


@settings(max_examples=150, deadline=None, suppress_health_check=SLOW_OK)
@given(prose_text)
def test_property_short_passages_only_remain_when_merging_is_impossible(
    text: str,
) -> None:
    passages = chunk_text(text)

    for before, passage in zip(passages, passages[1:], strict=False):
        too_short = len(passage.text) < MIN_CHARS
        assert not too_short or passage.char_end - before.char_start > MAX_CHARS


@settings(max_examples=150, deadline=None, suppress_health_check=SLOW_OK)
@given(prose_text, st.lists(st.integers(min_value=0, max_value=3000), max_size=8))
def test_property_a_passage_never_crosses_a_page(
    text: str, raw_starts: list[int]
) -> None:
    starts = sorted(raw_starts)

    passages = chunk_text(text, page_starts=starts)

    for passage in passages:
        assert passage.page == (bisect_right(starts, passage.char_start) or None)
        assert not any(passage.char_start < s < passage.char_end for s in starts)


@settings(max_examples=150, deadline=None, suppress_health_check=SLOW_OK)
@given(prose_text, st.lists(st.integers(min_value=0, max_value=3000), max_size=8))
def test_property_a_passage_never_crosses_a_unit(
    text: str, raw_starts: list[int]
) -> None:
    units = sorted({s for s in raw_starts if s < len(text)})

    passages = chunk_text(text, unit_starts=units)

    for passage in passages:
        for unit in units:
            assert not passage.char_start < unit < passage.char_end


@settings(max_examples=100, deadline=None, suppress_health_check=SLOW_OK)
@given(mixed_text)
def test_property_chunk_source_output_is_normalized_and_sliceable(raw: str) -> None:
    result = chunk_source(raw)

    assert_slices(result.text, result.passages)
    assert result.char_count == len(result.text)
    assert result.content_hash == hashlib.sha256(result.text.encode()).hexdigest()
