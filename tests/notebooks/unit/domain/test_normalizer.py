"""NB-6: text normalisation before chunking and the mapping of page offsets."""

import unicodedata

from app.modules.notebooks.domain.normalizer import NormalizedText, normalize_text

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

ATOMS = [
    "word",
    "Слово",
    "oʻ",
    "gʻoya",
    " ",
    "  ",
    "\t",
    "\n",
    "\n\n",
    "\r\n",
    "\r",
    "-\n",
    "-",
    "\x00",
    "\x07",
    "​",
    "﻿",
    "\xa0",
    "\xad",
    ".",
    "é",
]
texts = st.lists(st.sampled_from(ATOMS), max_size=60).map("".join)


def test_normalize_text_composes_unicode_to_nfc() -> None:
    result = normalize_text("é")

    assert result.text == "é"
    assert unicodedata.is_normalized("NFC", result.text)


def test_normalize_text_turns_crlf_and_cr_into_newlines() -> None:
    assert normalize_text("a\r\nb\rc\nd").text == "a\nb\nc\nd"


def test_normalize_text_treats_form_feed_and_line_separator_as_newline() -> None:
    assert normalize_text("a\x0cb c").text == "a\nb\nc"


def test_normalize_text_removes_control_characters_and_nul() -> None:
    assert normalize_text("a\x00b\x07c\x1fd\x7fe").text == "abcde"


def test_normalize_text_keeps_newline_and_tab() -> None:
    assert normalize_text("a\tb\nc").text == "a\tb\nc"


def test_normalize_text_removes_zero_width_characters_and_bom() -> None:
    assert normalize_text("﻿a​b‌c‍d⁠e").text == "abcde"


def test_normalize_text_replaces_no_break_space_with_space() -> None:
    assert normalize_text("a\xa0b c").text == "a b c"


def test_normalize_text_strips_trailing_spaces_of_every_line() -> None:
    assert normalize_text("a  \nb\t \n  c  ").text == "a\nb\n  c"


def test_normalize_text_collapses_three_newlines_to_one_blank_line() -> None:
    assert normalize_text("a\n\n\n\nb").text == "a\n\nb"


def test_normalize_text_keeps_one_blank_line() -> None:
    assert normalize_text("a\n\nb").text == "a\n\nb"


def test_normalize_text_collapses_blank_lines_that_only_hold_spaces() -> None:
    assert normalize_text("a\n \n  \n \nb").text == "a\n\nb"


def test_normalize_text_joins_hyphenated_russian_word() -> None:
    assert normalize_text("пере-\nнос слова").text == "перенос слова"


def test_normalize_text_joins_hyphenated_uzbek_word() -> None:
    assert normalize_text("oʻqi-\nvchi gʻoya").text == "oʻqivchi gʻoya"


def test_normalize_text_does_not_join_when_a_capital_follows() -> None:
    assert normalize_text("Север-\nСевер").text == "Север-\nСевер"


def test_normalize_text_does_not_join_when_a_digit_precedes_the_hyphen() -> None:
    assert normalize_text("page 5-\nnext").text == "page 5-\nnext"


def test_normalize_text_does_not_join_over_a_blank_line() -> None:
    assert normalize_text("word-\n\nnext").text == "word-\n\nnext"


def test_normalize_text_joins_after_trailing_spaces_are_stripped() -> None:
    assert normalize_text("пере- \nнос").text == "перенос"


def test_normalize_text_removes_soft_hyphen_and_joins_at_line_end() -> None:
    assert normalize_text("co\xadn\xad\nsole").text == "console"


def test_normalize_text_returns_empty_for_empty_input() -> None:
    assert normalize_text("") == NormalizedText("", ())


def test_normalize_text_returns_empty_for_spaces_only() -> None:
    assert normalize_text("   \t  ").text == ""


def test_normalize_text_keeps_one_character() -> None:
    assert normalize_text("x").text == "x"


def test_normalize_text_keeps_apostrophes_of_uzbek_letters() -> None:
    text = "Oʻzbekiston gʻoyalari ʼayn"

    assert normalize_text(text).text == text


def test_normalize_text_keeps_tab_separated_tables() -> None:
    table = "id\tname\tage\n1\tAli\t20\n2\tVali\t21"

    assert normalize_text(table).text == table


def test_marks_are_unchanged_when_nothing_is_rewritten() -> None:
    result = normalize_text("abc\ndef", [0, 4, 7])

    assert result.marks == (0, 4, 7)


def test_marks_shift_after_crlf_becomes_lf() -> None:
    result = normalize_text("ab\r\ncd\r\nef", [0, 4, 8])

    assert result.text == "ab\ncd\nef"
    assert result.marks == (0, 3, 6)
    assert [result.text[m] for m in result.marks[1:]] == ["c", "e"]


def test_marks_shift_after_removed_characters() -> None:
    result = normalize_text("a\x00\x00b​c", [3, 5])

    assert result.text == "abc"
    assert result.marks == (1, 2)


def test_marks_point_at_the_same_text_after_trailing_spaces_are_stripped() -> None:
    result = normalize_text("one   \ntwo   \nthree", [7, 14])

    assert result.text == "one\ntwo\nthree"
    assert [result.text[m:].split("\n")[0] for m in result.marks] == ["two", "three"]


def test_marks_inside_a_collapsed_newline_run_land_inside_the_result() -> None:
    result = normalize_text("a\n\n\n\nb", [1, 2, 3, 5])

    assert result.text == "a\n\nb"
    assert result.marks == (1, 2, 3, 3)


def test_mark_inside_a_removed_region_maps_to_its_start() -> None:
    result = normalize_text("ab​​​cd", [3, 4])

    assert result.text == "abcd"
    assert result.marks == (2, 2)


def test_marks_follow_a_hyphen_join() -> None:
    result = normalize_text("пере-\nнос\nдальше", [10])

    assert result.text == "перенос\nдальше"
    assert result.text[result.marks[0] :] == "дальше"


def test_marks_are_mapped_through_nfc_composition() -> None:
    result = normalize_text("éx", [2])

    assert result.text == "éx"
    assert result.marks == (1,)


def test_marks_are_clamped_to_the_input_and_the_output() -> None:
    result = normalize_text("ab\r\n", [-5, 100])

    assert result.text == "ab\n"
    assert result.marks == (0, 3)


def test_marks_at_the_end_of_the_text_stay_at_the_end() -> None:
    result = normalize_text("a\r\nb", [4])

    assert result.marks == (len(result.text),)


def test_long_run_of_spaces_is_handled_in_linear_time() -> None:
    result = normalize_text("a" + " " * 200_000 + "b")

    assert result.text == "a" + " " * 200_000 + "b"


@settings(max_examples=200, deadline=None)
@given(texts)
def test_property_normalization_is_idempotent(text: str) -> None:
    once = normalize_text(text).text

    assert normalize_text(once).text == once


@settings(max_examples=200, deadline=None)
@given(texts)
def test_property_normalized_text_has_no_forbidden_characters(text: str) -> None:
    out = normalize_text(text).text

    assert "\r" not in out
    assert "\x00" not in out
    assert "​" not in out
    assert "\n\n\n" not in out
    assert all(not line.endswith((" ", "\t")) for line in out.split("\n"))


@settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.data_too_large],
)
@given(texts, st.lists(st.integers(min_value=0, max_value=400), max_size=10))
def test_property_marks_stay_sorted_and_inside_the_result(
    text: str, raw_marks: list[int]
) -> None:
    marks = sorted(m for m in raw_marks if m <= len(text))

    result = normalize_text(text, marks)

    assert list(result.marks) == sorted(result.marks)
    assert all(0 <= m <= len(result.text) for m in result.marks)
    assert len(result.marks) == len(marks)


def test_marks_of_messy_pages_point_at_the_first_text_of_each_page() -> None:
    pages = [
        "Page one  \r\n \r\n\r\n",
        "Page two\x00\r\n\r\n\r\n\r\n",
        "Page\u200b three",
    ]
    offsets = [0, len(pages[0]), len(pages[0]) + len(pages[1])]

    result = normalize_text("".join(pages), offsets)

    assert [result.text[m:].split()[1] for m in result.marks] == ["one", "two", "three"]


def test_space_and_soft_hyphen_after_a_hyphen_join_in_one_pass() -> None:
    """Normalisation is idempotent for "word- \\xad\\nword" (found by hypothesis)."""
    once = normalize_text("word- \xad\nword").text

    assert once == "wordword"
    assert normalize_text(once).text == once
